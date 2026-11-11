"""Follow the beatmap currently selected in a running osu!stable client.

Read-only: the osu! process memory is only read (ReadProcessMemory), never written, and no
input is sent to the game. The signatures and offsets are the ones the open-source tosu
project uses for the stable client:
    base pattern  F8 01 74 04 83 65          beatmap object = [[base - 0xC]]
    beatmap + 0x6C -> .NET string             MD5 of the selected .osu file
    beatmap + 0x78 / + 0x90 -> .NET strings   song folder name / .osu file name (used only to find a
                                              map osu!.db does not list yet; ignored unless the file exists)
    state pattern 48 83 F8 04 73 1E           game state     = [[pattern - 0x4]]
A .NET string on the 32-bit runtime is: method table (4), length (4), UTF-16 characters.
"""
import ctypes
import logging
import threading
import time
from ctypes import wintypes

log = logging.getLogger('mpc.live')
BASE_PATTERN = bytes.fromhex('F80174048365')
STATE_PATTERN = bytes.fromhex('4883F804731E')

PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ = 0x0010
MEM_COMMIT = 0x1000
PAGE_NOACCESS, PAGE_GUARD = 0x01, 0x100
EXECUTABLE = 0x10 | 0x20 | 0x40 | 0x80
STILL_ACTIVE = 259
ADDRESS_LIMIT = 0xFFFF0000           # osu!stable is a 32-bit process

# osu!'s own screen ids (OsuModes); used for a status label only.
STATE_LABELS = {
    0: '메인 메뉴', 1: '에디터', 2: '플레이 중', 4: '곡 선택', 5: '곡 선택', 7: '결과 화면',
    11: '멀티 로비', 12: '멀티 방', 13: '곡 선택', 14: '결과 화면',
}


class _MBI(ctypes.Structure):
    _fields_ = [('BaseAddress', ctypes.c_void_p), ('AllocationBase', ctypes.c_void_p),
                ('AllocationProtect', wintypes.DWORD), ('PartitionId', wintypes.WORD),
                ('RegionSize', ctypes.c_size_t), ('State', wintypes.DWORD),
                ('Protect', wintypes.DWORD), ('Type', wintypes.DWORD)]


class _PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [('dwSize', wintypes.DWORD), ('cntUsage', wintypes.DWORD), ('th32ProcessID', wintypes.DWORD),
                ('th32DefaultHeapID', ctypes.c_size_t), ('th32ModuleID', wintypes.DWORD),
                ('cntThreads', wintypes.DWORD), ('th32ParentProcessID', wintypes.DWORD),
                ('pcPriClassBase', wintypes.LONG), ('dwFlags', wintypes.DWORD),
                ('szExeFile', wintypes.WCHAR * 260)]


def _kernel32():
    k = ctypes.WinDLL('kernel32', use_last_error=True)
    k.OpenProcess.restype = wintypes.HANDLE
    k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    k.ReadProcessMemory.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t,
                                    ctypes.POINTER(ctypes.c_size_t)]
    k.VirtualQueryEx.restype = ctypes.c_size_t
    k.VirtualQueryEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.POINTER(_MBI), ctypes.c_size_t]
    k.IsWow64Process.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)]
    k.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    k.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    k.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    k.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PROCESSENTRY32W)]
    k.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PROCESSENTRY32W)]
    return k


def find_pids(name='osu!.exe'):
    k = _kernel32()
    snap = k.CreateToolhelp32Snapshot(0x2, 0)
    if not snap or snap == wintypes.HANDLE(-1).value:
        return []
    pids = []
    try:
        entry = _PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(entry)
        ok = k.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            if entry.szExeFile.lower() == name.lower():
                pids.append(entry.th32ProcessID)
            ok = k.Process32NextW(snap, ctypes.byref(entry))
    finally:
        k.CloseHandle(snap)
    return pids


class AccessDenied(Exception):
    pass


class OsuProcess:
    """A handle on one osu! process, opened for reading only."""

    def __init__(self, pid, require_32bit=True):
        self.k = _kernel32()
        self.pid = pid
        self.handle = self.k.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
        if not self.handle:
            if ctypes.get_last_error() == 5:
                raise AccessDenied()
            raise OSError('OpenProcess failed (%d)' % ctypes.get_last_error())
        if require_32bit:
            wow = wintypes.BOOL()
            if not self.k.IsWow64Process(self.handle, ctypes.byref(wow)) or not wow.value:
                self.close()
                raise OSError('not a 32-bit process (osu!lazer?)')
        self.base = None
        self.state_at = None

    def close(self):
        if self.handle:
            self.k.CloseHandle(self.handle)
            self.handle = None

    def alive(self):
        code = wintypes.DWORD()
        return bool(self.handle and self.k.GetExitCodeProcess(self.handle, ctypes.byref(code))
                    and code.value == STILL_ACTIVE)

    def read(self, address, size):
        if not address or size <= 0:
            return None
        buf = ctypes.create_string_buffer(size)
        got = ctypes.c_size_t()
        if not self.k.ReadProcessMemory(self.handle, ctypes.c_void_p(address), buf, size, ctypes.byref(got)):
            return None
        return buf.raw[:got.value] if got.value == size else None

    def u32(self, address):
        data = self.read(address, 4)
        return int.from_bytes(data, 'little') if data else 0

    def string(self, pointer, limit=512):
        """A .NET string object at `pointer` (32-bit layout)."""
        head = self.read(pointer, 8)
        if not head:
            return None
        length = int.from_bytes(head[4:8], 'little', signed=True)
        if not 0 <= length <= limit:
            return None
        if length == 0:
            return ''
        data = self.read(pointer + 8, length * 2)
        return data.decode('utf-16-le', 'replace') if data else None

    def _regions(self, executable_only):
        address = 0x10000
        info = _MBI()
        while address < ADDRESS_LIMIT:
            if not self.k.VirtualQueryEx(self.handle, ctypes.c_void_p(address), ctypes.byref(info),
                                         ctypes.sizeof(info)):
                break
            base, size = info.BaseAddress or 0, info.RegionSize
            if size == 0:
                break
            protect = info.Protect
            if (info.State == MEM_COMMIT and not protect & (PAGE_NOACCESS | PAGE_GUARD) and protect
                    and (not executable_only or protect & EXECUTABLE)):
                yield base, size
            address = base + size

    def find(self, pattern, stop=None):
        """Address of the first occurrence of `pattern`: JIT code first, then everything readable."""
        chunk = 8 * 1024 * 1024
        for executable_only in (True, False):
            for base, size in self._regions(executable_only):
                offset = 0
                while offset < size:
                    if stop is not None and stop.is_set():
                        return None
                    part = min(chunk, size - offset)
                    data = self.read(base + offset, part)
                    if data:
                        at = data.find(pattern)
                        if at != -1:
                            return base + offset + at
                    offset += part - len(pattern) + 1 if part == chunk else part
        return None

    def locate(self, stop=None):
        """Find the signatures. They exist once osu! has compiled the code, i.e. after start-up."""
        if self.base is None:
            self.base = self.find(BASE_PATTERN, stop)
        if self.base is not None and self.state_at is None:
            self.state_at = self.find(STATE_PATTERN, stop)
        return self.base is not None

    def current_md5(self):
        """MD5 of the selected beatmap, '' when none is selected, None when it cannot be read."""
        if self.base is None:
            return None
        slot = self.u32(self.base - 0xC)
        if not slot:
            return None
        beatmap = self.u32(slot)
        if not beatmap:
            return ''
        text = self.string(self.u32(beatmap + 0x6C), 64)
        if text is None:
            return None
        text = text.lower()
        if len(text) == 32 and all(c in '0123456789abcdef' for c in text):
            return text
        return '' if text == '' else None

    def current_file(self):
        """(song folder name, .osu file name) of the selected beatmap, or None."""
        if self.base is None:
            return None
        slot = self.u32(self.base - 0xC)
        beatmap = self.u32(slot) if slot else 0
        if not beatmap:
            return None
        folder = self.string(self.u32(beatmap + 0x78), 400)
        name = self.string(self.u32(beatmap + 0x90), 400)
        if not folder or not name or not name.lower().endswith('.osu'):
            return None
        return folder, name

    def game_state(self):
        if self.state_at is None:
            return None
        slot = self.u32(self.state_at - 0x4)
        if not slot:
            return None
        data = self.read(slot, 4)
        value = int.from_bytes(data, 'little') if data else None
        return value if value is not None and 0 <= value < 64 else None


class LiveWatcher:
    """Background poller. `snapshot()` is safe to call from any thread."""

    def __init__(self, interval=0.4, pids=find_pids, require_32bit=True):
        self.interval = interval
        self._pids = pids
        self._require_32bit = require_32bit
        self._lock = threading.Lock()
        self._snap = {'running': False, 'readable': False, 'md5': None, 'state': None, 'label': '',
                      'problem': '', 'file': None}
        self._stop = threading.Event()
        self._thread = None
        self._process = None

    def start(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name='mpc-live', daemon=True)
            self._thread.start()

    def stop(self):
        self._stop.set()

    def snapshot(self):
        with self._lock:
            return dict(self._snap)

    def _set(self, **values):
        with self._lock:
            self._snap.update(values)

    def _run(self):
        next_search = next_locate = 0.0
        failures = tries = 0
        announced = False
        while not self._stop.wait(self.interval):
            now = time.monotonic()
            try:
                proc = self._process
                if proc is not None and not proc.alive():
                    proc.close()
                    proc = self._process = None
                if proc is None:
                    if now < next_search:
                        continue
                    next_search = now + 2.0
                    problem = ''
                    for pid in self._pids():
                        try:
                            proc = self._process = OsuProcess(pid, self._require_32bit)
                            break
                        except AccessDenied:
                            problem = 'access'
                        except OSError:
                            continue
                    if proc is None:
                        self._set(running=bool(problem), readable=False, md5=None, state=None, label='',
                                  problem=problem, file=None)
                        continue
                    next_locate = 0.0
                    failures = 0
                    tries = 0
                    log.info('osu! found (pid %d)', proc.pid)
                if proc.base is None:
                    if now >= next_locate:
                        next_locate = now + 4.0
                        proc.locate(self._stop)
                        tries += 1
                        if proc.base is not None:
                            log.info('osu! memory located (state %s)', 'ok' if proc.state_at else 'not found')
                        elif tries in (3, 15):
                            log.warning('osu! signature not found after %d tries', tries)
                    if proc.base is None:
                        self._set(running=True, readable=False, md5=None, state=None, label='', problem='starting',
                                  file=None)
                        continue
                md5 = proc.current_md5()
                if md5 is None:
                    failures += 1
                    if failures >= 12:                 # stale addresses: search again
                        proc.base = proc.state_at = None
                        failures = 0
                    continue
                failures = 0
                state = proc.game_state()
                changed = (md5 or None) != self._snap['md5']
                if md5 and not announced:
                    announced = True
                    log.info('reading the selected map from osu!')
                self._set(running=True, readable=True, md5=md5 or None, state=state,
                          label=STATE_LABELS.get(state, ''), problem='',
                          file=(proc.current_file() if md5 else None) if changed else self._snap['file'])
            except Exception:                           # never let the poller die
                log.exception('live reader error')
                if self._process is not None:
                    self._process.close()
                    self._process = None
                self._set(running=False, readable=False, md5=None, state=None, label='', problem='', file=None)
        if self._process is not None:
            self._process.close()
