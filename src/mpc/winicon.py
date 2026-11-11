"""Gives the app window the program's own icon at its real size.

The window is a Microsoft Edge / Chrome app window, and the browser builds the window icon (the one the
taskbar and Alt+Tab show) from the page's 16 px favicon, enlarged: it looks small and blurred next to
other programs. Here the icon file itself is loaded at the sizes Windows asks for and handed to that
window (WM_SETICON). The browser puts its own icon back whenever it refreshes the favicon, so this
keeps an eye on the window and hands the icon over again when that happens.

Only this program's own window is touched: a browser window whose title is exactly the program's title.
"""
import ctypes
import logging
import os
import threading
from ctypes import wintypes

log = logging.getLogger('mpc.winicon')
WM_GETICON, WM_SETICON = 0x007F, 0x0080
ICON_SMALL, ICON_BIG = 0, 1
SM_CXICON, SM_CXSMICON = 11, 49
IMAGE_ICON, LR_LOADFROMFILE = 1, 0x0010
SMTO_ABORTIFHUNG = 0x0002
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
BROWSERS = ('msedge.exe', 'chrome.exe')


class WindowIcon:
    def __init__(self, icon_path, title, interval=1.5):
        self.icon_path = str(icon_path)
        self.title = title
        self.interval = interval
        self._stop = threading.Event()
        self._thread = None
        self.applied = 0

    def start(self):
        if os.name != 'nt' or not os.path.isfile(self.icon_path) or self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name='mpc-winicon', daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    # ---- Win32

    def _setup(self):
        self.user32 = u = ctypes.WinDLL('user32', use_last_error=True)
        self.kernel32 = k = ctypes.WinDLL('kernel32', use_last_error=True)
        try:                                   # real pixel sizes on scaled displays
            ctypes.WinDLL('shcore').SetProcessDpiAwareness(2)
        except (OSError, AttributeError):
            pass
        u.LoadImageW.restype = wintypes.HANDLE
        u.LoadImageW.argtypes = [wintypes.HANDLE, wintypes.LPCWSTR, wintypes.UINT, ctypes.c_int, ctypes.c_int, wintypes.UINT]
        u.SendMessageTimeoutW.restype = ctypes.c_void_p
        u.SendMessageTimeoutW.argtypes = [wintypes.HWND, wintypes.UINT, ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT,
                                          wintypes.UINT, ctypes.POINTER(ctypes.c_void_p)]
        u.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        u.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        u.IsWindowVisible.argtypes = [wintypes.HWND]
        u.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        u.DestroyIcon.argtypes = [wintypes.HANDLE]
        k.OpenProcess.restype = wintypes.HANDLE
        k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
        k.CloseHandle.argtypes = [wintypes.HANDLE]
        self._enum_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        u.EnumWindows.argtypes = [self._enum_type, wintypes.LPARAM]
        sizes = {}
        for which, metric in ((ICON_BIG, SM_CXICON), (ICON_SMALL, SM_CXSMICON)):
            size = u.GetSystemMetrics(metric) or (32 if which == ICON_BIG else 16)
            handle = u.LoadImageW(None, self.icon_path, IMAGE_ICON, size, size, LR_LOADFROMFILE)
            if handle:
                sizes[which] = (handle, size)
        return sizes

    def _is_browser(self, hwnd):
        pid = wintypes.DWORD()
        self.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        handle = self.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
        if not handle:
            return False
        try:
            buf = ctypes.create_unicode_buffer(1024)
            size = wintypes.DWORD(len(buf))
            if not self.kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                return False
            return os.path.basename(buf.value).lower() in BROWSERS
        finally:
            self.kernel32.CloseHandle(handle)

    def _windows(self):
        found = []
        text, cls = ctypes.create_unicode_buffer(300), ctypes.create_unicode_buffer(80)

        def visit(hwnd, _):
            if self.user32.IsWindowVisible(hwnd):
                self.user32.GetWindowTextW(hwnd, text, len(text))
                if text.value == self.title:
                    self.user32.GetClassNameW(hwnd, cls, len(cls))
                    if cls.value.startswith('Chrome_WidgetWin') and self._is_browser(hwnd):
                        found.append(hwnd)
            return True

        self.user32.EnumWindows(self._enum_type(visit), 0)
        return found

    def _message(self, hwnd, message, wparam, lparam):
        result = ctypes.c_void_p()
        ok = self.user32.SendMessageTimeoutW(hwnd, message, wparam, lparam, SMTO_ABORTIFHUNG, 500, ctypes.byref(result))
        return result.value if ok else None

    def _run(self):
        try:
            icons = self._setup()
        except Exception:
            log.exception('window icon unavailable')
            return
        if not icons:
            log.warning('the icon file could not be loaded: %s', self.icon_path)
            return
        announced = False
        try:
            while not self._stop.wait(self.interval):
                for hwnd in self._windows():
                    for which, (handle, size) in icons.items():
                        if self._message(hwnd, WM_GETICON, which, 0) != handle:
                            self._message(hwnd, WM_SETICON, which, handle)
                            self.applied += 1
                    if not announced:
                        announced = True
                        log.info('window icon set (%s)', ', '.join('%dpx' % s for _, s in icons.values()))
        except Exception:
            log.exception('window icon watcher stopped')
        finally:
            if announced:
                log.info('window icon handed over %d time(s)', self.applied)
            for handle, _ in icons.values():
                self.user32.DestroyIcon(handle)
