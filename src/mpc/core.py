"""Application state and actions, independent of the interface: library, map details, export."""
import hashlib
import logging
import os
import re
import secrets
import shutil
import threading
import zipfile
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed

from . import audio, live, osufile, paths
from .calc import DanCalc
from .osudb import Library, detect_osu_folders

log = logging.getLogger('mpc.core')
ASSET_TYPES = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp',
               '.gif': 'image/gif', '.bmp': 'image/bmp', '.svg': 'image/svg+xml', '.mp3': 'audio/mpeg', '.ogg': 'audio/ogg',
               '.wav': 'audio/wav', '.flac': 'audio/flac', '.m4a': 'audio/mp4'}
IMAGE_NAME = re.compile(r'^(bg\d{2,3}|delete)\.(jpg|png)$')
BITRATES = (128, 160, 192, 256, 320)


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
        for key in ('dest', 'bitrate', 'osz', 'osuFolder', 'follow', 'libOpen', 'customSymbols', 'rateDest'):
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
        if not re.match(r'^[0-9a-f]{20}\.[a-z0-9]{2,5}$', asset or ''):
            return None
        target = paths.assets_dir() / asset
        return str(target) if target.is_file() else None

    # ---- export

    def export_begin(self, project):
        with self._lock:
            if self.job and self.job.state == 'running':
                raise ExportError('이미 내보내는 중입니다.')
            self.job = RateJob(self, project) if project.get('mode') == 'rate' else ExportJob(self, project)
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
        elif what == 'songs' and self.library.songs:
            target = str(self.library.songs)
        else:
            return False
        try:
            os.startfile(target)
            return True
        except OSError:
            return False


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
            base, n = version, 2
            while version.lower() in used:
                version = '%s (%d)' % (base, n)
                n += 1
            used.add(version.lower())
            self.entries.append({
                'uid': str(raw.get('uid') or i), 'index': i, 'path': lib['path'], 'info': info, 'source': source,
                'rate': rate, 'follow': bool(raw.get('followPitch')), 'version': version,
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
        room = max(20, 235 - len(self.folder) - len(stem))
        return stem + osufile.safe_name(version, room, False) + '].osu'

    def _write(self, name, text):
        self.created.append(os.path.join(self.folder, name))
        with open(os.path.join(self.folder, name), 'w', encoding='utf-8', newline='') as f:
            f.write(text)

    def _chart_meta(self, e):
        return dict(self.meta, Version=e['version'])

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
        self.created.append(os.path.join(self.folder, 'delete.mp3'))
        preview = audio.render_delete_audio(self.runner, os.path.join(self.folder, 'delete.mp3'), seconds,
                                            d['clip'], start, d['length'])
        keys = Counter(e['info']['keys'] for e in self.entries).most_common(1)[0][0]
        text = osufile.delete_difficulty(dict(self.meta, Version=d['name']), 'delete.mp3',
                                         d['image'] if d['image'] in self.images else '', keys,
                                         int(d['minutes'] * 60000) + 1000, preview)
        self._write(self._chart_name(d['name']), text)
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
        for name in sorted(os.listdir(folder)):
            packed = name.lower().endswith(('.mp3', '.jpg', '.png', '.ogg'))
            z.write(os.path.join(folder, name), name,
                    compress_type=zipfile.ZIP_STORED if packed else zipfile.ZIP_DEFLATED)
