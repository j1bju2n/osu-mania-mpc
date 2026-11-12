"""Application state and actions, independent of the interface: library, map details, export."""
import hashlib
import json
import logging
import os
import re
import secrets
import shutil
import threading
import time
import zipfile
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed

from . import __version__, audio, live, osufile, paths
from .calc import DanCalc
from .osudb import Library, detect_osu_folders

log = logging.getLogger('mpc.core')
ASSET_TYPES = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp',
               '.gif': 'image/gif', '.bmp': 'image/bmp', '.svg': 'image/svg+xml', '.mp3': 'audio/mpeg', '.ogg': 'audio/ogg',
               '.wav': 'audio/wav', '.flac': 'audio/flac', '.m4a': 'audio/mp4'}
IMAGE_NAME = re.compile(r'^(bg\d{2,3}|delete)\.(jpg|png)$')
BITRATES = (128, 160, 192, 256, 320)
ASSET_ID = re.compile(r'^[0-9a-f]{20}\.[a-z0-9]{2,5}$')
SAVE_EXT = '.mpcpack'
SKIP_FILES = {'thumbs.db', 'desktop.ini', '.ds_store'}
# what the upload server accepts inside a set (osu-server-beatmap-submission, BeatmapPackageParser)
UPLOADABLE = {'.osb', '.mp3', '.ogg', '.wav', '.jpg', '.jpeg', '.png', '.avi', '.flv', '.mp4', '.m4v', '.mpg',
              '.mov', '.wmv', '.webm', '.mkv'}
FILENAME_MAX = 150                                     # the server refuses longer .osu file names


def _asset_ids(node, out):
    """Every user file (picture, music) named anywhere inside a project."""
    if isinstance(node, dict):
        for value in node.values():
            _asset_ids(value, out)
    elif isinstance(node, list):
        for value in node:
            _asset_ids(value, out)
    elif isinstance(node, str):
        name = node[6:] if node.startswith('asset:') else node
        if ASSET_ID.match(name):
            out.add(name)


class ExportError(Exception):
    pass


class Core:
    def __init__(self):
        self.settings = paths.load_json(paths.settings_path(), {})
        self.library = Library()
        self.calc = DanCalc()
        self.ffmpeg = paths.find_ffmpeg()
        self.watcher = live.LiveWatcher()
        self._info = {}
        self._lock = threading.Lock()
        self.job = None

    # ---- lifecycle

    def start(self):
        threading.Thread(target=self._load_library, name='mpc-library', daemon=True).start()
        self.watcher.start()

    def _load_library(self):
        folder = self.settings.get('osuFolder')
        candidates = ([folder] if folder else []) + [str(p) for p in detect_osu_folders()]
        if not candidates:
            self.library.status = 'error'
            self.library.message = 'osu! 폴더를 찾지 못했습니다. 폴더 위치를 직접 지정해 주세요.'
            return
        try:
            self.library.load(candidates[0])
        except Exception as exc:                          # the interface must still come up
            log.exception('library load failed')
            self.library.status = 'error'
            self.library.message = '맵 목록을 읽지 못했습니다: %s' % exc

    def reload_library(self, folder=None):
        if self.library.status == 'loading':
            return False
        if folder:
            self.settings['osuFolder'] = folder
            self.save_settings({})
        self._info.clear()
        self.library.status = 'loading'
        self.start()
        return True

    def shutdown(self):
        self.watcher.stop()
        if self.job:
            self.job.cancel()
        self.calc.close()

    def save_settings(self, changes):
        for key in ('dest', 'bitrate', 'osz', 'osuFolder', 'follow', 'libOpen', 'customSymbols', 'rateDest', 'volume'):
            if key in changes:
                self.settings[key] = changes[key]
        try:
            paths.save_json(paths.settings_path(), self.settings)
        except OSError:
            log.warning('settings not saved')

    # ---- what the interface reads

    def state(self):
        lib = self.library
        return {
            'library': {'status': lib.status, 'message': lib.message, 'count': len(lib.entries),
                        'folder': str(lib.folder or ''), 'songs': str(lib.songs or ''),
                        'keys': sorted(lib.key_counts().items()), 'player': lib.player},
            'tools': {'ffmpeg': bool(self.ffmpeg), 'calc': self.calc.available},
            'settings': {'dest': self.settings.get('dest', 'packs'), 'bitrate': self.settings.get('bitrate', 192),
                         'osz': bool(self.settings.get('osz', False)),
                         'follow': bool(self.settings.get('follow', True)),
                         'libOpen': bool(self.settings.get('libOpen', False)),
                         'rateDest': self.settings.get('rateDest', 'source'),
                         'volume': self.settings.get('volume', 50),
                         'customSymbols': [s for s in self.settings.get('customSymbols') or [] if isinstance(s, dict)]},
            'packsDir': str(paths.packs_dir()),
            'project': paths.load_json(paths.project_path(), {}),
        }

    def live_state(self):
        """The map selected in a running osu!, if it can be read and is a mania map we know."""
        snap = self.watcher.snapshot()
        md5, known = snap['md5'], False
        if md5 and self.library.status == 'ready':
            if not self.library.get(md5) and snap.get('file'):
                self.library.adopt(snap['file'][0])
            known = bool(self.library.get(md5))
        return {'running': snap['running'], 'readable': snap['readable'], 'md5': md5, 'known': known,
                'label': snap['label'], 'problem': snap['problem']}

    @staticmethod
    def _row(e):
        return {'md5': e['md5'], 'title': e['title'], 'artist': e['artist'], 'creator': e['creator'],
                'version': e['version'], 'keys': e['keys'], 'lengthMs': e['total_ms'], 'notes': e['notes'],
                'lns': e['lns']}

    def search(self, query, keys, offset):
        hits, total = self.library.search(query, keys, offset)
        return {'total': total, 'offset': offset, 'rows': [self._row(e) for e in hits]}

    def _file_info(self, entry):
        info = self._info.get(entry['md5'])
        if info is None:
            info = osufile.info(entry['path'])
            if len(self._info) > 2000:
                self._info.clear()
            self._info[entry['md5']] = info
        return info

    def map_detail(self, md5):
        entry = self.library.get(md5)
        if not entry:
            return None
        try:
            info = self._file_info(entry)
        except OSError:
            return None
        audio_file = osufile.audio_path(entry['path'], info['audio'])
        return {
            'md5': entry['md5'], 'title': info['title'] or entry['title'], 'titleU': info['title_u'],
            'artist': info['artist'] or entry['artist'], 'artistU': info['artist_u'],
            'creator': info['creator'], 'version': info['version'], 'keys': info['keys'],
            'source': info['source'], 'tags': info['tags'],
            'lengthMs': info['last_ms'], 'firstMs': info['first_ms'], 'preview': info['preview'],
            'bpm': info['bpm'], 'bpmMin': info['bpm_min'], 'bpmMax': info['bpm_max'],
            'notes': info['notes'], 'lns': info['lns'], 'od': info['od'], 'hp': info['hp'],
            'hasBg': bool(osufile.background_path(entry['path'], info['background'])),
            'hasAudio': bool(audio_file),
            'audioExt': os.path.splitext(audio_file)[1].lower().lstrip('.') if audio_file else '',
        }

    def rating(self, md5, rate):
        entry = self.library.get(md5)
        if not entry:
            return None
        return self.calc.summary(entry['md5'], entry['path'], rate)

    def background_of(self, md5):
        entry = self.library.get(md5)
        if not entry:
            return None
        try:
            return osufile.background_path(entry['path'], self._file_info(entry)['background'])
        except OSError:
            return None

    def audio_of(self, md5):
        entry = self.library.get(md5)
        if not entry:
            return None
        try:
            return osufile.audio_path(entry['path'], self._file_info(entry)['audio'])
        except OSError:
            return None

    # ---- project and user files

    def save_project(self, project):
        try:
            paths.save_json(paths.project_path(), project)
            return True
        except OSError:
            return False

    def backup_project(self):
        """Keep the project as it is now in project.backup.json (called before it is cleared)."""
        try:
            source = paths.project_path()
            if source.is_file():
                shutil.copyfile(str(source), str(source.with_name('project.backup.json')))
            return True
        except OSError:
            return False

    def store_asset(self, name, data):
        ext = os.path.splitext(name or '')[1].lower()
        if ext not in ASSET_TYPES or not data:
            return None
        asset = hashlib.sha1(data).hexdigest()[:20] + ext
        folder = paths.assets_dir()
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / asset
        if not target.is_file():
            target.write_bytes(data)
        return asset

    def asset_path(self, asset):
        if not ASSET_ID.match(asset or ''):
            return None
        target = paths.assets_dir() / asset
        return str(target) if target.is_file() else None

    def missing(self, md5s):
        """Which of these maps this osu! folder does not have. None while the list is still being read."""
        if self.library.status != 'ready':
            return None
        return [m for m in md5s if isinstance(m, str) and not self.library.get(m)]

    # ---- saved packs (the `save` folder beside the program)

    @staticmethod
    def _save_file(name):
        name = osufile.safe_name(' '.join(str(name or '').split()), 80)
        return name, paths.saves_dir() / (name + SAVE_EXT)

    def save_list(self):
        folder = paths.saves_dir()
        out = []
        try:
            files = [p for p in folder.iterdir() if p.is_file() and p.name.lower().endswith(SAVE_EXT)]
        except OSError:
            files = []
        for path in files:
            row = {'name': path.name[:-len(SAVE_EXT)], 'title': '', 'maps': None, 'edit': False,
                   'savedAt': int(path.stat().st_mtime * 1000), 'size': path.stat().st_size}
            try:
                with zipfile.ZipFile(str(path)) as z:
                    info = json.loads(z.read('info.json').decode('utf-8'))
                for key in ('title', 'maps', 'edit', 'savedAt'):
                    if key in info:
                        row[key] = info[key]
            except (OSError, ValueError, KeyError, zipfile.BadZipFile):
                row['broken'] = True
            out.append(row)
        out.sort(key=lambda r: r['savedAt'], reverse=True)
        return {'folder': str(folder), 'saves': out}

    def save_write(self, name, project):
        """One file per pack: the project and every picture / music file it uses, so it opens anywhere."""
        if not isinstance(project, dict) or not isinstance(project.get('entries'), list):
            return {'ok': False, 'message': '저장할 팩 구성이 없습니다.'}
        name, target = self._save_file(name)
        project = dict(project)
        project.pop('rc', None)                           # the rate changer is not part of a pack
        project['saveName'] = name
        assets = set()
        _asset_ids(project, assets)
        symbols = [s for s in self.settings.get('customSymbols') or []
                   if isinstance(s, dict) and s.get('asset') in assets]
        info = {'name': name, 'title': str((project.get('pack') or {}).get('title') or ''),
                'maps': len(project['entries']), 'edit': bool(project.get('edit')),
                'savedAt': int(time.time() * 1000), 'app': __version__}
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = str(target) + '.tmp'
            with zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED) as z:
                z.writestr('info.json', json.dumps(info, ensure_ascii=False))
                z.writestr('project.json', json.dumps(project, ensure_ascii=False))
                z.writestr('symbols.json', json.dumps(symbols, ensure_ascii=False))
                for asset in sorted(assets):
                    path = self.asset_path(asset)
                    if path:
                        z.write(path, 'assets/' + asset, compress_type=zipfile.ZIP_STORED)
            os.replace(tmp, str(target))
        except OSError as exc:
            return {'ok': False, 'message': '저장하지 못했습니다: %s' % exc}
        log.info('pack saved: %d maps, %d files', info['maps'], len(assets))
        return {'ok': True, 'name': name, 'file': str(target)}

    def save_exists(self, name):
        return self._save_file(name)[1].is_file()

    def save_read(self, name):
        name, target = self._save_file(name)
        try:
            with zipfile.ZipFile(str(target)) as z:
                project = json.loads(z.read('project.json').decode('utf-8'))
                try:
                    symbols = json.loads(z.read('symbols.json').decode('utf-8'))
                except (KeyError, ValueError):
                    symbols = []
                folder = paths.assets_dir()
                folder.mkdir(parents=True, exist_ok=True)
                for item in z.infolist():
                    asset = item.filename[7:] if item.filename.startswith('assets/') else ''
                    if not ASSET_ID.match(asset) or os.path.splitext(asset)[1] not in ASSET_TYPES:
                        continue
                    if item.file_size > 200 << 20 or (folder / asset).is_file():
                        continue
                    data = z.read(item)
                    if hashlib.sha1(data).hexdigest()[:20] != asset[:20]:      # not the file its name says
                        continue
                    (folder / asset).write_bytes(data)
        except (OSError, ValueError, KeyError, zipfile.BadZipFile):
            return {'ok': False, 'message': '이 저장 파일을 읽지 못했습니다.'}
        if not isinstance(project, dict) or not isinstance(project.get('entries'), list):
            return {'ok': False, 'message': '이 저장 파일에는 팩 구성이 없습니다.'}
        mine = [s for s in self.settings.get('customSymbols') or [] if isinstance(s, dict)]
        have = {s.get('asset') for s in mine}
        names = {str(s.get('name') or '').strip().lower() for s in mine}
        added = False
        for s in symbols if isinstance(symbols, list) else []:
            if not isinstance(s, dict) or not ASSET_ID.match(str(s.get('asset') or '')) or s['asset'] in have:
                continue
            label = str(s.get('name') or 'symbol').strip()[:40] or 'symbol'
            base, n = label, 2
            while label.lower() in names:                 # the same name already means another picture here
                label = '%s %d' % (base, n)
                n += 1
            names.add(label.lower())
            have.add(s['asset'])
            mine.append({'asset': s['asset'], 'name': label})
            added = True
        if added:
            self.save_settings({'customSymbols': mine})
        project['saveName'] = name
        entries = [e for e in project['entries'] if isinstance(e, dict)]
        return {'ok': True, 'name': name, 'project': project, 'symbols': mine,
                'missing': self.missing([str(e.get('md5') or '') for e in entries])}

    def save_delete(self, name):
        target = self._save_file(name)[1]
        try:
            target.unlink()
            return True
        except OSError:
            return False

    # ---- an uploaded set, read for rebuilding

    def set_detail(self, md5):
        entry = self.library.get(md5)
        if not entry:
            return None
        folder = os.path.dirname(entry['path'])
        try:
            found = scan_set(folder)
        except OSError:
            return None
        self.library.include(folder)                       # every difficulty of it can now be opened by md5
        self._info.clear()
        found.pop('path')                                  # full paths stay on this side (they end up in save files)
        found.pop('media')
        for slot in found['slots']:
            slot.pop('path')
        return found

    # ---- export

    def export_begin(self, project):
        with self._lock:
            if self.job and self.job.state == 'running':
                raise ExportError('이미 내보내는 중입니다.')
            kind = {'rate': RateJob, 'edit': EditJob}.get(project.get('mode'), ExportJob)
            self.job = kind(self, project)
            return self.job.describe()

    def export_image(self, job_id, name, data):
        job = self.job
        if not job or job.id != job_id or job.state != 'waiting' or name not in job.allowed:
            return False
        target = os.path.join(job.folder, name)
        job.created.append(target)
        with open(target, 'wb') as f:
            f.write(data)
        job.images.add(name)
        return True

    def export_run(self, job_id):
        job = self.job
        if not job or job.id != job_id or job.state != 'waiting':
            return False
        job.start()
        return True

    def export_status(self):
        return self.job.status() if self.job else {'state': 'none'}

    def export_cancel(self):
        if self.job:
            self.job.cancel()

    def open_folder(self, what):
        if what == 'pack' and self.job and self.job.state == 'done':
            target = self.job.folder
        elif what == 'packs':
            target = str(paths.packs_dir())
            os.makedirs(target, exist_ok=True)
        elif what == 'saves':
            target = str(paths.saves_dir())
            os.makedirs(target, exist_ok=True)
        elif what == 'songs' and self.library.songs:
            target = str(self.library.songs)
        else:
            return False
        try:
            os.startfile(target)
            return True
        except OSError:
            return False


def scan_set(folder):
    """Every difficulty file of one song folder, with what an update of the uploaded set needs to know."""
    slots, audios, media = [], set(), set()
    for name in sorted(os.listdir(folder), key=str.lower):
        if not name.lower().endswith('.osu'):
            continue
        path = os.path.join(folder, name)
        try:
            with open(path, 'rb') as f:
                raw = f.read()
            info = osufile.info_from_text(osufile.decode(raw))
        except (OSError, ValueError):
            continue
        audio_file = osufile.audio_path(path, info['audio'])
        background = osufile.background_path(path, info['background'])
        span = info['last_ms'] - info['first_ms']
        kind = 'other' if info['mode'] != 3 else 'delete' if info['notes'] <= 2 and span >= 240000 else 'map'
        for used in (info['audio'], info['background']):
            if used:
                media.add(used.replace('\\', '/').lower())
        if info['audio']:
            audios.add(info['audio'].lower())
        slots.append({
            'file': name, 'md5': hashlib.md5(raw).hexdigest(), 'id': max(0, info['beatmap_id']),
            'setId': info['set_id'], 'kind': kind, 'mode': info['mode'], 'keys': info['keys'],
            'version': info['version'], 'title': info['title'], 'titleU': info['title_u'],
            'artist': info['artist'], 'artistU': info['artist_u'], 'creator': info['creator'],
            'source': info['source'], 'tags': info['tags'], 'audio': info['audio'],
            'hasAudio': bool(audio_file), 'hasBg': bool(background), 'lengthMs': info['last_ms'],
            'notes': info['notes'], 'format': info['format'], 'path': path,
        })
    ids = Counter(s['setId'] for s in slots if s['setId'] > 0)
    others = 0
    for base, _dirs, files in os.walk(folder):
        for name in files:
            rel = os.path.relpath(os.path.join(base, name), folder).replace('\\', '/').lower()
            if not rel.endswith('.osu') and rel not in media and name.lower() not in SKIP_FILES:
                others += 1
    return {'folder': os.path.basename(folder), 'path': folder, 'setId': ids.most_common(1)[0][0] if ids else -1,
            'mixedIds': len(ids) > 1, 'audios': len(audios), 'others': others, 'media': sorted(media),
            'slots': slots}


def _unique_folder(root, name):
    target = os.path.join(root, name)
    n = 2
    while os.path.exists(target):
        target = os.path.join(root, '%s (%d)' % (name, n))
        n += 1
    return target


class ExportJob:
    """One export: created (folder made), then images arrive from the interface, then the audio and
    the .osu files are produced on a worker thread."""
    mode = 'pack'

    def __init__(self, core, project):
        self.created = []                # every file this job wrote
        self.own_folder = True           # the folder itself was made by this job
        self.allowed = set()             # image names the interface may send
        self.core = core
        self.id = secrets.token_hex(8)
        self.state = 'waiting'
        self.error = ''
        self.step = ''
        self.done = 0
        self.total = 0
        self.images = set()
        self.osz = ''
        self.size = 0
        self.runner = audio.Runner(core.ffmpeg)
        self._thread = None
        self._parse(project)
        self._open_folder()

    def _open_folder(self):
        root = self.dest_root
        os.makedirs(root, exist_ok=True)
        self.folder = _unique_folder(root, osufile.safe_name('%s - %s' % (self.meta['Artist'], self.meta['Title'])))
        os.makedirs(self.folder)
        self.allowed = {e['image'] for e in self.entries}
        if self.delete:
            self.allowed.add(self.delete['image'])

    # ---- reading the request

    def _parse(self, project):
        core = self.core
        if not core.ffmpeg:
            raise ExportError('ffmpeg.exe를 찾지 못했습니다. 프로그램과 같은 폴더에 ffmpeg.exe를 넣어 주세요.')
        pack = project.get('pack') or {}
        title = str(pack.get('title') or '').strip()
        if not title:
            raise ExportError('맵팩 이름을 입력해 주세요.')
        artist = str(pack.get('artist') or '').strip() or 'Various Artists'
        creator = str(pack.get('creator') or '').strip()
        if not creator:
            raise ExportError('제작자(Creator) 이름을 입력해 주세요.')
        tags = ' '.join(str(pack.get('tags') or '').split())
        self.meta = {'Title': title, 'TitleUnicode': str(pack.get('titleUnicode') or '').strip() or title,
                     'Artist': artist, 'ArtistUnicode': str(pack.get('artistUnicode') or '').strip() or artist,
                     'Creator': creator, 'Source': str(pack.get('source') or '').strip(), 'Tags': tags}
        self.reset_ids = bool(pack.get('resetIds', True))
        self.od = _optional_number(pack.get('od'), 0, 10)
        self.hp = _optional_number(pack.get('hp'), 0, 10)
        try:
            bitrate = int(project.get('bitrate') or 192)
        except (TypeError, ValueError):
            bitrate = 192
        self.bitrate = bitrate if bitrate in BITRATES else 192
        self.image_ext = 'png' if project.get('imageFormat') == 'png' else 'jpg'
        self.want_osz = bool(project.get('osz'))
        dest = project.get('dest')
        if dest == 'songs' and core.library.songs and os.path.isdir(core.library.songs):
            self.dest_root = str(core.library.songs)
        else:
            self.dest_root = str(paths.packs_dir())

        entries = project.get('entries') if isinstance(project.get('entries'), list) else []
        if not entries:
            raise ExportError('팩에 넣은 맵이 없습니다.')
        self.entries = []
        used = set()
        for i, raw in enumerate(entries):
            lib = core.library.get(str(raw.get('md5') or ''))
            if not lib:
                raise ExportError('%d번째 맵을 osu! 폴더에서 찾지 못했습니다.' % (i + 1))
            info = osufile.info(lib['path'])
            source = osufile.audio_path(lib['path'], info['audio'])
            if not source:
                raise ExportError('%s [%s]의 오디오 파일이 없습니다.' % (info['title'], info['version']))
            try:
                rate = round(float(raw.get('rate') or 1.0), 2)
            except (TypeError, ValueError):
                rate = 1.0
            if not 0.5 <= rate <= 2.0:
                raise ExportError('%s: 배속은 0.50 ~ 2.00 사이여야 합니다.' % info['title'])
            version = ' '.join(str(raw.get('version') or '').split()) or info['version'] or 'Map %d' % (i + 1)
            own_tags = raw.get('tags')                  # this map's own tags, when the pack sets them per map
            base, n = version, 2
            while version.lower() in used:
                version = '%s (%d)' % (base, n)
                n += 1
            used.add(version.lower())
            self.entries.append({
                'uid': str(raw.get('uid') or i), 'index': i, 'path': lib['path'], 'info': info, 'source': source,
                'rate': rate, 'follow': bool(raw.get('followPitch')), 'version': version,
                'tags': ' '.join(own_tags.split()) if isinstance(own_tags, str) else None,
                'image': 'bg%02d.%s' % (i + 1, self.image_ext), 'audio': '', 'status': 'wait', 'report': None,
            })

        d = project.get('delete') or {}
        self.delete = None
        if d.get('enabled', True):
            name = ' '.join(str(d.get('name') or '').split()) or 'delete'
            if name.lower() in used:
                raise ExportError('delete 난이도명이 다른 난이도명과 겹칩니다.')
            try:
                minutes = float(d.get('minutes') or 10)
            except (TypeError, ValueError):
                minutes = 10.0
            minutes = min(30.0, max(5.0, minutes))
            preview = d.get('preview') or {}
            clip, start = None, 0.0
            mode = preview.get('mode')
            if mode == 'entry':
                chosen = next((e for e in self.entries if e['uid'] == str(preview.get('uid'))), None)
                if chosen:
                    clip = chosen['source']
                    start = chosen['info']['preview'] / 1000.0 if chosen['info']['preview'] >= 0 else -1.0
            elif mode == 'file':
                clip = core.asset_path(str(preview.get('asset') or ''))
                try:
                    start = max(0.0, float(preview.get('start') or 0))
                except (TypeError, ValueError):
                    start = 0.0
                if not clip:
                    raise ExportError('delete 난이도에 넣을 미리듣기 음악 파일을 찾지 못했습니다.')
            try:
                length = float(preview.get('length') or 30)
            except (TypeError, ValueError):
                length = 30.0
            self.delete = {'name': name, 'minutes': minutes, 'clip': clip, 'start': start,
                           'length': min(120.0, max(5.0, length)), 'image': 'delete.%s' % self.image_ext}

    def describe(self):
        return {'job': self.id, 'folder': self.folder, 'imageExt': self.image_ext,
                'images': [{'uid': e['uid'], 'name': e['image']} for e in self.entries if e['image']],
                'deleteImage': self.delete['image'] if self.delete else None}

    # ---- running

    def start(self):
        self.state = 'running'
        self._thread = threading.Thread(target=self._run, name='mpc-export', daemon=True)
        self._thread.start()

    def cancel(self):
        if self.state in ('running', 'waiting'):
            self.runner.cancel()
            if self.state == 'waiting':
                self.state = 'cancelled'
                self._discard()

    def _discard(self):
        if self.own_folder:
            shutil.rmtree(self.folder, ignore_errors=True)   # the folder was created by this job
            return
        for path in self.created:                            # someone else's folder: only our own files
            try:
                os.remove(path)
            except OSError:
                pass

    def _run(self):
        try:
            self._audio()
            self._charts()
            if self.delete:
                self._delete_difficulty()
            self.size = sum(os.path.getsize(p) for p in set(self.created) if os.path.isfile(p))
            if self.want_osz:
                self.step = '.osz 파일을 만드는 중'
                self.osz = self.folder + '.osz'
                _zip_folder(self.folder, self.osz)
            self.step = ''
            self.state = 'done'
            log.info('exported %d difficulties to %s', len(self.entries), self.folder)
        except audio.Cancelled:
            self.state = 'cancelled'
            self._discard()
        except Exception as exc:
            log.exception('export failed')
            self.error = str(exc) or type(exc).__name__
            self.state = 'error'
            self._discard()

    def _audio(self):
        groups = {}
        for e in self.entries:
            if e.get('keep_audio'):
                continue
            key = (os.path.normcase(e['source']), e['rate'], e['follow'] or e['rate'] == 1.0)
            groups.setdefault(key, []).append(e)
        self.total = len(groups) + (1 if self.delete else 0)
        self.step = '오디오를 변환하는 중'
        work = str(paths.work_dir())

        def one(members):
            first = members[0]
            name = first.get('audio_name') or 'audio%02d.mp3' % (first['index'] + 1)
            for m in members:
                m['status'] = 'work'
            self.created.append(os.path.join(self.folder, name))
            report = audio.render(self.runner, first['source'], os.path.join(self.folder, name), first['rate'],
                                  first['follow'], self.bitrate, work)
            return members, name, report

        workers = max(1, min(4, (os.cpu_count() or 2) // 2))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(one, members) for members in groups.values()]
            try:
                for future in as_completed(futures):
                    members, name, report = future.result()
                    for m in members:
                        m['audio'] = name
                        m['report'] = report
                        m['status'] = 'done'
                    self.done += 1
            except BaseException:
                self.runner.cancel()
                for future in futures:
                    future.cancel()
                raise

    def _chart_name(self, version):
        m = self.meta
        stem = '%s - %s (%s) [' % (osufile.safe_name(m['Artist'], 60, False), osufile.safe_name(m['Title'], 80, False),
                                   osufile.safe_name(m['Creator'], 40, False))
        room = max(20, min(235 - len(self.folder), FILENAME_MAX) - len(stem) - 5)
        return stem + osufile.safe_name(version, room, False) + '].osu'

    def _write(self, name, text):
        self.created.append(os.path.join(self.folder, name))
        with open(os.path.join(self.folder, name), 'w', encoding='utf-8', newline='') as f:
            f.write(text)

    def _chart_meta(self, e):
        meta = dict(self.meta, Version=e['version'])
        if e.get('tags') is not None:
            meta['Tags'] = e['tags']
        return meta

    def _chart_background(self, e):
        return e['image'] if e['image'] in self.images else ''

    def _charts(self):
        self.step = '난이도 파일을 쓰는 중'
        names = {n.lower() for n in os.listdir(self.folder)}
        for e in self.entries:
            text = osufile.transform(osufile.read(e['path']), rate=e['rate'], audio_name=e['audio'],
                                     background_name=self._chart_background(e),
                                     meta=self._chart_meta(e), od=self.od, hp=self.hp, reset_ids=self.reset_ids)
            name = self._chart_name(e['version'])
            n = 2
            while name.lower() in names:
                name = self._chart_name('%s %d' % (e['version'], n))
                n += 1
            names.add(name.lower())
            self._write(name, text)

    def _delete_difficulty(self):
        d = self.delete
        self.step = 'delete 난이도를 만드는 중'
        seconds = d['minutes'] * 60.0 + 5.0
        start = d['start']
        if d['clip'] and start < 0:                       # the map had no preview point: a little way in
            start = self.runner.probe(d['clip'])['duration'] * 0.4
        sound = d.get('audio') or 'delete.mp3'
        self.created.append(os.path.join(self.folder, sound))
        preview = audio.render_delete_audio(self.runner, os.path.join(self.folder, sound), seconds,
                                            d['clip'], start, d['length'])
        keys = Counter(e['info']['keys'] for e in self.entries).most_common(1)[0][0]
        text = osufile.delete_difficulty(dict(self.meta, Version=d['name']), sound,
                                         d['image'] if d['image'] in self.images else '', keys,
                                         int(d['minutes'] * 60000) + 1000, preview, ids=d.get('ids'))
        name = self._chart_name(d['name'])
        taken = {n.lower() for n in os.listdir(self.folder)}
        n = 2
        while name.lower() in taken:
            name = self._chart_name('%s %d' % (d['name'], n))
            n += 1
        self._write(name, text)
        self.done += 1

    def status(self):
        return {
            'job': self.id, 'state': self.state, 'step': self.step, 'done': self.done, 'total': self.total,
            'error': self.error, 'folder': self.folder, 'osz': self.osz, 'size': self.size,
            'delete': bool(self.delete), 'mode': self.mode, 'inPlace': not self.own_folder,
            'items': [{'uid': e['uid'], 'version': e['version'], 'rate': e['rate'], 'status': e['status'],
                       'report': e['report']} for e in self.entries],
        }


class RateJob(ExportJob):
    """Practice rates of one map: new difficulties next to the original (nothing there is replaced),
    or in a folder of their own."""
    mode = 'rate'

    def _parse(self, project):
        core = self.core
        if not core.ffmpeg:
            raise ExportError('ffmpeg.exe를 찾지 못했습니다. 프로그램과 같은 폴더에 ffmpeg.exe를 넣어 주세요.')
        lib = core.library.get(str(project.get('md5') or ''))
        if not lib:
            raise ExportError('맵을 osu! 폴더에서 찾지 못했습니다.')
        info = osufile.info(lib['path'])
        source = osufile.audio_path(lib['path'], info['audio'])
        if not source:
            raise ExportError('이 맵의 오디오 파일이 없습니다.')
        self.src = {'path': lib['path'], 'info': info, 'dir': os.path.dirname(lib['path'])}
        self.meta = {'Artist': info['artist'], 'Title': info['title'], 'Creator': info['creator']}   # file names only
        self.reset_ids = True
        self.od = _optional_number(project.get('od'), 0, 10)
        self.hp = None
        try:
            bitrate = int(project.get('bitrate') or 192)
        except (TypeError, ValueError):
            bitrate = 192
        self.bitrate = bitrate if bitrate in BITRATES else 192
        self.image_ext = 'jpg'
        self.want_osz = False
        self.delete = None
        self.own_folder = project.get('dest') == 'packs'
        self.dest_root = str(paths.packs_dir())
        rows = project.get('entries') if isinstance(project.get('entries'), list) else []
        if not rows:
            raise ExportError('만들 배속이 없습니다.')
        used = set()
        if not self.own_folder:                               # names already taken in the map's folder
            for name in os.listdir(self.src['dir']):
                if name.lower().endswith('.osu'):
                    try:
                        used.add(osufile.info(os.path.join(self.src['dir'], name))['version'].lower())
                    except (OSError, ValueError):
                        continue
        self.entries = []
        for i, raw in enumerate(rows):
            try:
                rate = round(float(raw.get('rate')), 2)
            except (TypeError, ValueError):
                raise ExportError('배속 값이 올바르지 않습니다.')
            if not 0.5 <= rate <= 2.0:
                raise ExportError('배속은 0.50 ~ 2.00 사이여야 합니다.')
            version = ' '.join(str(raw.get('version') or '').split()) or '%s %.2fx' % (info['version'], rate)
            base, n = version, 2
            while version.lower() in used:
                version = '%s (%d)' % (base, n)
                n += 1
            used.add(version.lower())
            self.entries.append({
                'uid': str(raw.get('uid') or i), 'index': i, 'path': lib['path'], 'info': info, 'source': source,
                'rate': rate, 'follow': bool(raw.get('followPitch')), 'version': version,
                'want_image': bool(raw.get('image')), 'image': '', 'audio': '', 'status': 'wait', 'report': None,
            })

    def _open_folder(self):
        info = self.src['info']
        if self.own_folder:
            os.makedirs(self.dest_root, exist_ok=True)
            self.folder = _unique_folder(self.dest_root, osufile.safe_name(
                '%s - %s [%s] rates' % (info['artist'], info['title'], info['version'])))
            os.makedirs(self.folder)
        else:
            self.folder = self.src['dir']
        taken = {n.lower() for n in os.listdir(self.folder)}

        def free(name):
            stem, ext = os.path.splitext(name)
            candidate, n = name, 2
            while candidate.lower() in taken:
                candidate = '%s_%d%s' % (stem, n, ext)
                n += 1
            taken.add(candidate.lower())
            return candidate

        audio_stem = osufile.safe_name(os.path.splitext(os.path.basename(info['audio']))[0], 60)
        image_stem = osufile.safe_name(os.path.splitext(os.path.basename(info['background'] or 'bg'))[0], 60)
        for e in self.entries:
            unity = abs(e['rate'] - 1.0) < 1e-9
            if unity and not self.own_folder:                 # same folder, same speed: the original audio
                e['audio'] = info['audio']
                e['keep_audio'] = True
                e['status'] = 'done'
                e['report'] = {'mode': 'keep', 'trimmed': False, 'shift_ms': None, 'spread_ms': None,
                               'residual_ms': None}
            else:
                e['audio_name'] = free('%s_%.2fx%s.mp3' % (audio_stem, e['rate'],
                                                           '_pitch' if e['follow'] and not unity else ''))
            if e['want_image']:
                e['image'] = free('%s_%.2fx.jpg' % (image_stem, e['rate']))
        self.allowed = {e['image'] for e in self.entries if e['image']}

    def _chart_meta(self, e):
        return {'Version': e['version']}

    def _chart_background(self, e):
        return e['image'] if e['image'] and e['image'] in self.images else None      # None: the original's

    def _charts(self):
        if self.own_folder:                                   # a folder of its own needs the original picture
            original = osufile.background_path(self.src['path'], self.src['info']['background'])
            if original and any(self._chart_background(e) is None for e in self.entries):
                target = os.path.join(self.folder, os.path.basename(original))
                if not os.path.exists(target):
                    self.created.append(target)
                    shutil.copyfile(original, target)
        super()._charts()


class EditJob(ExportJob):
    """A set that is already uploaded, rebuilt in a folder of its own. Every difficulty carries the set's
    online id; one that stands where an original difficulty stood carries that difficulty's id, so the
    upload updates the set instead of making a new one. The original folder is only read.

    A difficulty left as it was (same file, 1.00x) is copied line for line with its own audio; only its
    picture, its ids and (when asked) its metadata lines change."""
    mode = 'edit'

    def _parse(self, project):
        core = self.core
        edit = project.get('edit') if isinstance(project.get('edit'), dict) else {}
        songs = core.library.songs
        source = osufile.inside_dir(str(songs), str(edit.get('folder') or '')) if songs else None
        if not source:
            raise ExportError('원본 맵셋 폴더를 osu! Songs 폴더에서 찾지 못했습니다.')
        self.src = scan_set(source)
        self.set_id = self.src['setId']
        if self.set_id <= 0:
            raise ExportError('이 맵셋에는 온라인 ID(BeatmapSetID)가 없습니다. 업로드된 적이 없는 맵셋은 새 팩으로 만들어 주세요.')
        if int(edit.get('setId') or 0) != self.set_id:
            raise ExportError('불러온 뒤에 원본 맵셋이 바뀌었습니다. "기존 맵팩 수정"에서 다시 불러와 주세요.')
        core.library.include(source)
        self.remake = bool(edit.get('thumbs', True))
        self.unify = bool(edit.get('unify'))
        super()._parse(dict(project, dest='packs'))
        self.reset_ids = False
        self.dest_root = str(paths.packs_dir())
        online = {s['id']: s for s in self.src['slots'] if s['id'] > 0}
        taken = set()

        def claim(value, what):
            try:
                slot = int(value or 0)
            except (TypeError, ValueError):
                slot = 0
            if slot and slot not in online:
                raise ExportError('%s: 이 맵셋에 없는 BeatmapID(%d)입니다. 다시 불러와 주세요.' % (what, slot))
            if slot in taken:
                raise ExportError('%s: 같은 BeatmapID(%d)를 두 난이도가 쓰려고 합니다.' % (what, slot))
            if slot:
                taken.add(slot)
            return slot

        home = os.path.normcase(os.path.realpath(source))
        for e, raw in zip(self.entries, project.get('entries') or []):
            e['beatmap_id'] = claim(raw.get('slot'), e['version'])
            inside = os.path.normcase(os.path.realpath(os.path.dirname(e['path']))) == home
            e['asis'] = inside and abs(e['rate'] - 1.0) < 1e-9
        if self.delete:
            self.delete['ids'] = (claim(edit.get('deleteSlot'), self.delete['name']), self.set_id)
        wanted = {str(n).lower() for n in edit.get('carry') or []}
        self.carry = [s for s in self.src['slots'] if s['kind'] == 'other' and s['file'].lower() in wanted]
        for s in self.carry:
            if s['id']:
                taken.add(s['id'])
        self.removed = [s for s in self.src['slots'] if s['id'] > 0 and s['id'] not in taken]

    def _open_folder(self):
        os.makedirs(self.dest_root, exist_ok=True)
        name = self.src['folder']
        lead = re.match(r'^(\d+)', name)
        if not lead or int(lead.group(1)) != self.set_id:  # osu! reads leading digits of the folder as the set id
            name = '%d %s - %s' % (self.set_id, self.meta['Artist'], self.meta['Title'])
        self.folder = _unique_folder(self.dest_root, osufile.safe_name(name))
        os.makedirs(self.folder)
        source = self.src['path']
        self.skipped = 0
        self.copies = {}                                  # name inside the set -> file to copy as it is

        def keep(path):
            if path:
                self.copies[os.path.relpath(os.path.realpath(path), os.path.realpath(source))] = path

        for e in self.entries:
            if not e['asis']:
                continue
            e['keep_audio'] = True
            e['audio'] = e['info']['audio']
            e['status'] = 'done'
            e['report'] = {'mode': 'keep', 'trimmed': False, 'shift_ms': None, 'spread_ms': None, 'residual_ms': None}
            keep(e['source'])
            if not self.remake:
                e['image'] = ''                           # its own picture stays
                keep(osufile.background_path(e['path'], e['info']['background']))
        for s in self.carry:
            keep(osufile.audio_path(s['path']))
            keep(osufile.background_path(s['path']))
        media = set(self.src['media'])
        for base, _dirs, files in os.walk(source):        # hitsounds, storyboard files and the like
            for name in files:
                path = os.path.join(base, name)
                rel = os.path.relpath(path, source)
                if (name.lower().endswith('.osu') or name.lower() in SKIP_FILES
                        or rel.replace('\\', '/').lower() in media):
                    continue
                if os.path.splitext(name)[1].lower() not in UPLOADABLE:
                    self.skipped += 1                     # the upload would be refused with it inside
                    continue
                self.copies[rel] = path
        used = {rel.replace('\\', '/').lower() for rel in self.copies}

        def free(name):
            stem, ext = os.path.splitext(name)
            candidate, n = name, 2
            while candidate.lower() in used:
                candidate = '%s_%d%s' % (stem, n, ext)
                n += 1
            used.add(candidate.lower())
            return candidate

        for e in self.entries:
            if e['image']:
                e['image'] = free(e['image'])
            if not e['asis']:
                e['audio_name'] = free('audio%02d.mp3' % (e['index'] + 1))
        self.allowed = {e['image'] for e in self.entries if e['image']}
        if self.delete:
            self.delete['image'] = free(self.delete['image'])
            self.delete['audio'] = free('delete.mp3')
            self.allowed.add(self.delete['image'])

    def _audio(self):
        self.step = '원본 파일을 복사하는 중'
        for rel, path in self.copies.items():
            target = os.path.join(self.folder, rel)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            self.created.append(target)
            shutil.copyfile(path, target)
        super()._audio()

    def _charts(self):
        self.step = '난이도 파일을 쓰는 중'
        names = {n.lower() for n in os.listdir(self.folder)}
        # osu! and the server find an online difficulty by its file name: a name that belonged to one
        # BeatmapID must not turn up under another
        reserved = {s['file'].lower(): s['id'] for s in self.src['slots'] if s['id'] > 0}

        def free(name, again, own=0):
            n = 2
            while name.lower() in names or reserved.get(name.lower(), own) != own:
                name = again(n)
                n += 1
            names.add(name.lower())
            return name

        for e in self.entries:
            ids = (e['beatmap_id'], self.set_id)
            if e['asis']:
                picture = e['image'] if e['image'] and e['image'] in self.images else None
                if e['image'] and not picture:            # no new picture arrived: its own one is needed
                    original = osufile.background_path(e['path'], e['info']['background'])
                    if original:
                        target = os.path.join(self.folder, os.path.relpath(
                            os.path.realpath(original), os.path.realpath(self.src['path'])))
                        if not os.path.exists(target):
                            os.makedirs(os.path.dirname(target), exist_ok=True)
                            self.created.append(target)
                            shutil.copyfile(original, target)
                text = osufile.patch(osufile.read(e['path']), background_name=picture,
                                     meta=self._chart_meta(e) if self.unify else {'Version': e['version']},
                                     od=self.od if self.unify else None, hp=self.hp if self.unify else None, ids=ids)
                stem = os.path.splitext(os.path.basename(e['path']))[0]
                name = free(stem + '.osu', lambda n: '%s %d.osu' % (stem, n), e['beatmap_id'])
            else:
                text = osufile.transform(osufile.read(e['path']), rate=e['rate'], audio_name=e['audio'],
                                         background_name=self._chart_background(e), meta=self._chart_meta(e),
                                         od=self.od, hp=self.hp, reset_ids=False, ids=ids)
                name = free(self._chart_name(e['version']), lambda n: self._chart_name('%s %d' % (e['version'], n)),
                            e['beatmap_id'])
            self._write(name, text)
        for s in self.carry:                              # not a mania difficulty: carried over untouched
            stem = os.path.splitext(s['file'])[0]
            name = free(s['file'], lambda n: '%s %d.osu' % (stem, n), s['id'])
            self.created.append(os.path.join(self.folder, name))
            shutil.copyfile(s['path'], os.path.join(self.folder, name))

    def status(self):
        out = super().status()
        rows = [{'version': e['version'], 'id': e['beatmap_id'], 'how': 'asis' if e['asis'] else 'made'}
                for e in self.entries]
        if self.delete:
            rows.append({'version': self.delete['name'], 'id': self.delete['ids'][0], 'how': 'delete'})
        rows += [{'version': s['version'], 'id': s['id'], 'how': 'carry'} for s in self.carry]
        out['edit'] = {'setId': self.set_id, 'rows': rows, 'copied': len(self.copies), 'skipped': self.skipped,
                       'removed': [{'version': s['version'], 'id': s['id']} for s in self.removed]}
        return out


def _optional_number(value, low, high):
    if value in (None, ''):
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return min(high, max(low, value))


def _zip_folder(folder, target):
    with zipfile.ZipFile(target, 'w') as z:
        for base, _dirs, files in os.walk(folder):
            for name in sorted(files):
                path = os.path.join(base, name)
                packed = name.lower().endswith(('.mp3', '.jpg', '.jpeg', '.png', '.ogg', '.mp4', '.avi', '.flv'))
                z.write(path, os.path.relpath(path, folder).replace('\\', '/'),
                        compress_type=zipfile.ZIP_STORED if packed else zipfile.ZIP_DEFLATED)
