"""The beatmap library: osu!.db (fast, complete) plus a direct read of song folders it does not list yet.

Read-only. Nothing here writes to the osu! folder.
"""
import hashlib
import logging
import os
import struct
from pathlib import Path

from . import osufile

log = logging.getLogger('mpc.osudb')


class _Reader:
    def __init__(self, data):
        self.d = data
        self.p = 0

    def take(self, fmt, size):
        value = struct.unpack_from(fmt, self.d, self.p)[0]
        self.p += size
        return value

    def u8(self):
        return self.take('<B', 1)

    def i16(self):
        return self.take('<h', 2)

    def i32(self):
        return self.take('<i', 4)

    def i64(self):
        return self.take('<q', 8)

    def f32(self):
        return self.take('<f', 4)

    def f64(self):
        return self.take('<d', 8)

    def skip(self, n):
        self.p += n

    def string(self):
        marker = self.d[self.p]
        self.p += 1
        if marker == 0:
            return ''
        if marker != 0x0b:
            raise ValueError('bad string marker at %d' % (self.p - 1))
        n = shift = 0
        while True:
            b = self.d[self.p]
            self.p += 1
            n |= (b & 0x7f) << shift
            if b < 0x80:
                break
            shift += 7
        raw = bytes(self.d[self.p:self.p + n])
        self.p += n
        return raw.decode('utf-8', 'replace')


def read_osu_db(path, songs):
    """mania beatmaps listed in osu!.db -> (list of entries, player name)."""
    with open(path, 'rb') as f:
        r = _Reader(memoryview(f.read()))
    version = r.i32()
    r.i32()                     # folder count
    r.u8()                      # account unlocked
    r.i64()                     # unlock date
    player = r.string()
    count = r.i32()
    pair = 10 if version >= 20250107 else 14
    out = []
    for _ in range(count):
        if version < 20191106:
            r.i32()
        artist = r.string()
        artist_u = r.string()
        title = r.string()
        title_u = r.string()
        creator = r.string()
        diff = r.string()
        audio = r.string()
        md5 = r.string()
        osu_name = r.string()
        r.u8()                                  # ranked status
        circles = r.take('<H', 2)
        sliders = r.take('<H', 2)
        r.skip(2)                               # spinners
        r.i64()                                 # last modification
        if version < 20140609:
            r.skip(1)
            cs = float(r.u8())
            r.skip(2)
        else:
            r.f32()
            cs = r.f32()
            r.f32()
            r.f32()
        r.f64()                                 # slider velocity
        if version >= 20140609:
            for _mode in range(4):
                r.skip(r.i32() * pair)
        r.i32()                                 # drain time (s)
        total = r.i32()
        preview = r.i32()
        r.skip(r.i32() * 17)                    # timing points
        r.i32()                                 # difficulty id
        set_id = r.i32()
        r.i32()                                 # thread id
        r.skip(4)                               # grades
        r.i16()                                 # local offset
        r.f32()                                 # stack leniency
        mode = r.u8()
        source = r.string()
        tags = r.string()
        r.i16()                                 # online offset
        r.string()                              # title font
        r.u8()                                  # unplayed
        r.i64()                                 # last played
        r.u8()                                  # osz2
        folder = r.string()
        r.i64()                                 # last checked
        r.skip(5)
        if version < 20140609:
            r.skip(2)
        r.i32()
        r.u8()                                  # mania scroll speed
        if mode != 3 or not md5 or not folder or not osu_name:
            continue
        out.append({
            'md5': md5.lower(), 'artist': artist, 'artist_u': artist_u, 'title': title, 'title_u': title_u,
            'creator': creator, 'version': diff, 'audio': audio, 'keys': int(round(cs)),
            'total_ms': max(0, total), 'preview': preview, 'set_id': set_id, 'source': source, 'tags': tags,
            'notes': circles + sliders, 'lns': sliders, 'folder': folder,
            'path': os.path.join(str(songs), folder, osu_name),
        })
    return out, player


def scan_folder(folder):
    """mania difficulties found directly in one song folder."""
    out = []
    try:
        names = [n for n in os.listdir(folder) if n.lower().endswith('.osu')]
    except OSError:
        return out
    for name in names:
        path = os.path.join(folder, name)
        try:
            with open(path, 'rb') as f:
                raw = f.read()
            info = osufile.info_from_text(osufile.decode(raw))
        except (OSError, ValueError):
            continue
        if info['mode'] != 3:
            continue
        out.append({
            'md5': hashlib.md5(raw).hexdigest(), 'artist': info['artist'], 'artist_u': info['artist_u'],
            'title': info['title'], 'title_u': info['title_u'], 'creator': info['creator'],
            'version': info['version'], 'audio': info['audio'], 'keys': info['keys'],
            'total_ms': info['last_ms'], 'preview': info['preview'], 'set_id': info['set_id'],
            'source': info['source'], 'tags': info['tags'], 'notes': info['notes'], 'lns': info['lns'],
            'folder': os.path.basename(folder), 'path': path,
        })
    return out


# ---------------------------------------------------------------- installation folder

def songs_dir(folder):
    """Songs location. osu! lets the user move it with BeatmapDirectory in osu!.<user>.cfg."""
    folder = Path(folder)
    candidates = []
    try:
        user = os.environ.get('USERNAME') or ''
        if user:
            candidates.append(folder / ('osu!.' + user + '.cfg'))
        candidates += sorted(p for p in folder.glob('osu!.*.cfg') if p not in candidates)
    except OSError:
        pass
    for cfg in candidates:
        try:
            for line in cfg.read_text(encoding='utf-8', errors='replace').splitlines():
                key, sep, value = line.partition('=')
                if sep and key.strip() == 'BeatmapDirectory' and value.strip():
                    target = Path(value.strip())
                    if not target.is_absolute():
                        target = folder / target
                    if target.is_dir():
                        return target
        except OSError:
            continue
    return folder / 'Songs'


def valid_osu_folder(path):
    try:
        folder = Path(path).expanduser().resolve()
    except (OSError, ValueError, RuntimeError):
        return None
    if not folder.is_dir():
        return None
    return folder if songs_dir(folder).is_dir() else None


def detect_osu_folders():
    found = []

    def add(path):
        match = valid_osu_folder(path) if path else None
        if match and match not in found:
            found.append(match)

    add(Path(os.environ.get('LOCALAPPDATA') or (Path.home() / 'AppData' / 'Local')) / 'osu!')
    try:
        import winreg
        for name in ('osustable.File.osz', 'osu', 'osu!'):
            try:
                with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, name + r'\shell\open\command') as key:
                    command = winreg.QueryValueEx(key, '')[0]
                exe = command.split('"')[1] if command.startswith('"') else command.split(' ')[0]
                add(Path(exe).parent)
            except (OSError, IndexError):
                continue
    except ImportError:
        pass
    for letter in 'CDEFGH':
        for sub in ('osu!', r'Games\osu!', r'Program Files\osu!', r'Program Files (x86)\osu!'):
            add(Path(letter + ':\\') / sub)
    return found


# ---------------------------------------------------------------- library

class Library:
    """All mania difficulties of one osu! folder, searchable."""

    def __init__(self):
        self.folder = None
        self.songs = None
        self.entries = []
        self.by_md5 = {}
        self.player = ''
        self.status = 'idle'            # idle | loading | ready | error
        self.message = ''
        self.extra = 0                  # difficulties read straight from folders
        self._tried = set()             # folders already read on request (see adopt)

    def load(self, folder):
        self.status = 'loading'
        self.message = ''
        folder = valid_osu_folder(folder)
        if not folder:
            self.status = 'error'
            self.message = 'osu! 폴더를 찾지 못했습니다.'
            return
        self.folder = folder
        self.songs = songs_dir(folder)
        entries, player = [], ''
        db = folder / 'osu!.db'
        if db.is_file():
            try:
                entries, player = read_osu_db(db, self.songs)
            except (OSError, ValueError, struct.error, IndexError) as exc:
                log.warning('osu!.db unreadable: %s', exc)
                entries = []
        listed = {e['folder'].lower() for e in entries}
        extra = []
        try:
            with os.scandir(self.songs) as it:
                missing = [e.path for e in it if e.is_dir() and e.name.lower() not in listed]
        except OSError:
            missing = []
        # with a readable osu!.db only new folders are left; without one this reads everything
        for path in missing:
            extra.extend(scan_folder(path))
        seen = {e['md5'] for e in entries}
        extra = [e for e in extra if e['md5'] not in seen]
        self.extra = len(extra)
        entries.extend(extra)
        for e in entries:
            self._index(e)
        self._tried = set()
        entries.sort(key=lambda e: (e['title'].lower(), e['artist'].lower(), e['creator'].lower(), e['notes']))
        self.entries = entries
        self.by_md5 = {e['md5']: e for e in entries}
        self.player = player
        self.status = 'ready'
        log.info('library: %d mania difficulties (%d read from folders)', len(entries), self.extra)

    def get(self, md5):
        return self.by_md5.get((md5 or '').lower())

    @staticmethod
    def _index(e):
        e['hay'] = ' '.join((e['title'], e['title_u'], e['artist'], e['artist_u'], e['creator'],
                             e['version'], e['tags'], e['source'])).lower()

    def adopt(self, folder_name):
        """Read one song folder that osu!.db does not list yet (a map imported while osu! is running)."""
        if self.status != 'ready' or not folder_name or folder_name in self._tried:
            return
        self._tried.add(folder_name)
        songs = os.path.realpath(str(self.songs))
        folder = os.path.realpath(os.path.join(songs, folder_name))
        try:
            if os.path.commonpath([songs, folder]) != songs or not os.path.isdir(folder):
                return
        except ValueError:
            return
        for e in scan_folder(folder):
            if e['md5'] not in self.by_md5:
                self._index(e)
                self.entries.append(e)
                self.by_md5[e['md5']] = e
                self.extra += 1

    def search(self, query, keys=0, offset=0, limit=120):
        words = [w for w in (query or '').lower().split() if w]
        hits = []
        total = 0
        for e in self.entries:
            if keys and e['keys'] != keys:
                continue
            hay = e['hay']
            if all(w in hay for w in words):
                if offset <= total < offset + limit:
                    hits.append(e)
                total += 1
        return hits, total

    def key_counts(self):
        counts = {}
        for e in self.entries:
            counts[e['keys']] = counts.get(e['keys'], 0) + 1
        return counts
