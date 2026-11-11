"""Local UI host: serves the interface on 127.0.0.1 and opens it in an app window.

The interface is plain HTML/CSS/JS (the `web` folder), shown in a chromeless Microsoft Edge or
Chrome window (`--app=`); with neither installed it opens in the default browser.
Nothing is reachable from other machines: the server binds to the loopback address only, checks
the Host header, and requires a per-run random token on every API call.
"""
import json
import logging
import os
import re
import secrets
import socketserver
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import APP_BYLINE, APP_NAME, __version__, paths
from .core import ASSET_TYPES, Core, ExportError

log = logging.getLogger('mpc.server')
STATIC = {'/': 'index.html', '/app.css': 'app.css', '/app.js': 'app.js', '/editor.js': 'editor.js',
          '/parts.js': 'parts.js'}
TYPES = {'.html': 'text/html; charset=utf-8', '.css': 'text/css; charset=utf-8',
         '.js': 'text/javascript; charset=utf-8', '.ico': 'image/x-icon',
         '.svg': 'image/svg+xml', '.webp': 'image/webp'}
IMAGE_TYPES = {'.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png', '.bmp': 'image/bmp',
               '.gif': 'image/gif', '.webp': 'image/webp'}
AUDIO_TYPES = {'.mp3': 'audio/mpeg', '.ogg': 'audio/ogg', '.wav': 'audio/wav', '.flac': 'audio/flac'}
BADGE = re.compile(r'^/dans/(reform|ln|6k|7k)/([a-z0-9-]+\.(?:svg|webp))$')
MAX_JSON = 16 << 20
MAX_UPLOAD = 80 << 20


class _Server(ThreadingHTTPServer):
    daemon_threads = True

    def server_bind(self):                      # skip the reverse DNS lookup HTTPServer does
        socketserver.TCPServer.server_bind(self)
        self.server_name = '127.0.0.1'
        self.server_port = self.server_address[1]


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    core = None
    token = ''
    app = None

    def log_message(self, *args):
        pass

    # ---- helpers

    def _send(self, status, body=b'', content_type='application/json; charset=utf-8', cache='no-store',
              extra=None):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', cache)
        self.send_header('X-Content-Type-Options', 'nosniff')
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != 'HEAD':
            try:
                self.wfile.write(body)
            except OSError:
                pass

    def _json(self, obj, status=200):
        self._send(status, json.dumps(obj, ensure_ascii=False, separators=(',', ':')).encode('utf-8'))

    def _allowed(self, query):
        host = self.headers.get('Host') or ''
        if host != '127.0.0.1:%d' % self.server.server_address[1]:
            return False
        given = self.headers.get('X-MPC-Token') or (query.get('t') or [''])[0]
        return secrets.compare_digest(given, self.token)

    def _raw(self, limit):
        try:
            length = int(self.headers.get('Content-Length') or 0)
        except ValueError:
            length = 0
        if not 0 <= length <= limit:
            return None
        return self.rfile.read(length) if length else b''

    def _file(self, path, types, cache='private, max-age=600'):
        """A file from disk, honouring a Range request (audio elements seek with them)."""
        try:
            size = os.path.getsize(path)
            if size > 400 << 20:
                return self._send(404)
            start, end = 0, size - 1
            rng = re.match(r'bytes=(\d*)-(\d*)$', self.headers.get('Range') or '')
            partial = False
            if rng and (rng.group(1) or rng.group(2)):
                if rng.group(1):
                    start = int(rng.group(1))
                    end = min(int(rng.group(2)), size - 1) if rng.group(2) else size - 1
                else:
                    start = max(0, size - int(rng.group(2)))
                if start > end or start >= size:
                    return self._send(416, extra={'Content-Range': 'bytes */%d' % size})
                partial = True
            with open(path, 'rb') as f:
                f.seek(start)
                data = f.read(end - start + 1)
        except (OSError, ValueError):
            return self._send(404)
        kind = types.get(os.path.splitext(path)[1].lower(), 'application/octet-stream')
        extra = {'Accept-Ranges': 'bytes'}
        if partial:
            extra['Content-Range'] = 'bytes %d-%d/%d' % (start, end, size)
        self._send(206 if partial else 200, data, kind, cache, extra)

    def _hold(self):
        """A response that never ends: it stays open for as long as the window does, so the program
        knows the window is there without depending on timers the browser may slow down."""
        self.send_response(200)
        self.send_header('Content-Type', 'text/plain; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Connection', 'close')
        self.end_headers()
        self.close_connection = True
        app = self.app
        app.hold(1)
        try:
            while not app.stopping.wait(2.0):
                self.wfile.write(b'.')
                self.wfile.flush()
                app.touch()
        except OSError:
            pass
        finally:
            app.hold(-1)

    # ---- GET

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        path = parsed.path
        web = str(paths.web_dir())
        if path in STATIC or path == '/favicon.ico':
            name = STATIC.get(path, 'mpc.ico')
            try:
                with open(os.path.join(web, name), 'rb') as f:
                    data = f.read()
            except OSError:
                return self._send(404)
            return self._send(200, data, TYPES.get(os.path.splitext(name)[1], 'application/octet-stream'))
        badge = BADGE.match(path)
        if badge:
            try:
                with open(os.path.join(web, 'dans', badge.group(1), badge.group(2)), 'rb') as f:
                    data = f.read()
            except OSError:
                return self._send(404)
            return self._send(200, data, TYPES[os.path.splitext(path)[1]], 'private, max-age=86400')
        if not path.startswith('/api/'):
            return self._send(404)
        if not self._allowed(query):
            return self._json({'error': 'forbidden'}, 403)
        core = self.core
        self.app.touch()

        def arg(name):
            return (query.get(name) or [''])[0]

        if path == '/api/state':
            state = core.state()
            state['app'] = {'name': APP_NAME, 'byline': APP_BYLINE, 'version': __version__}
            return self._json(state)
        if path == '/api/hold':
            return self._hold()
        if path == '/api/live':
            return self._json(core.live_state())
        if path == '/api/library':
            return self._json(core.state()['library'])
        if path == '/api/search':
            try:
                keys, offset = int(arg('keys') or 0), max(0, int(arg('offset') or 0))
            except ValueError:
                keys, offset = 0, 0
            return self._json(core.search(arg('q'), keys, offset))
        if path == '/api/map':
            detail = core.map_detail(arg('md5'))
            return self._json(detail) if detail else self._json({'error': 'not found'}, 404)
        if path == '/api/rating':
            try:
                rate = float(arg('rate') or 1.0)
            except ValueError:
                rate = 1.0
            if not 0.5 <= rate <= 2.0:
                rate = 1.0
            return self._json({'rating': core.rating(arg('md5'), rate)})
        if path == '/api/bg':
            target = core.background_of(arg('md5'))
            return self._file(target, IMAGE_TYPES) if target else self._send(404)
        if path == '/api/audio':
            target = core.audio_of(arg('md5'))
            return self._file(target, AUDIO_TYPES) if target else self._send(404)
        if path == '/api/asset':
            target = core.asset_path(arg('id'))
            return self._file(target, ASSET_TYPES, 'private, max-age=86400') if target else self._send(404)
        if path == '/api/export/status':
            return self._json(core.export_status())
        self._json({'error': 'not found'}, 404)

    # ---- POST

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        path = parsed.path
        binary = path in ('/api/asset', '/api/export/image')
        raw = self._raw(MAX_UPLOAD if binary else MAX_JSON)
        if not path.startswith('/api/') or not self._allowed(query):
            return self._json({'error': 'forbidden'}, 403)
        if raw is None:
            return self._json({'error': 'too large'}, 413)
        core = self.core
        self.app.touch()

        def arg(name):
            return (query.get(name) or [''])[0]

        if path == '/api/asset':
            asset = core.store_asset(arg('name'), raw)
            return self._json({'ok': bool(asset), 'id': asset})
        if path == '/api/export/image':
            return self._json({'ok': core.export_image(arg('job'), arg('name'), raw)})
        try:
            body = json.loads(raw or b'{}')
        except ValueError:
            body = {}
        if not isinstance(body, dict):
            body = {}
        result = {'ok': True}
        if path == '/api/ping':
            pass
        elif path == '/api/bye':
            self.app.window_closed()
        elif path == '/api/project':
            result['ok'] = core.save_project(body)
        elif path == '/api/project/backup':
            result['ok'] = core.backup_project()
        elif path == '/api/settings':
            core.save_settings(body)
        elif path == '/api/library/reload':
            result['ok'] = core.reload_library(str(body.get('folder') or '') or None)
        elif path == '/api/export/begin':
            try:
                result.update(core.export_begin(body))
            except ExportError as exc:
                result = {'ok': False, 'message': str(exc)}
            except OSError as exc:
                result = {'ok': False, 'message': '내보낼 폴더를 만들지 못했습니다: %s' % exc}
        elif path == '/api/export/run':
            result['ok'] = core.export_run(str(body.get('job') or ''))
        elif path == '/api/export/cancel':
            core.export_cancel()
        elif path == '/api/open':
            result['ok'] = core.open_folder(str(body.get('what') or ''))
        else:
            return self._json({'error': 'not found'}, 404)
        self._json(result)


class App:
    """Owns the HTTP server, the Core and the window; decides when to exit."""
    quiet_after_hold = 20        # seconds without any sign of the page once it has held a connection
    quiet_without_hold = 150     # the same for a page that never managed to hold one

    def __init__(self, core=None, port=0, token=None):
        self.core = core or Core()
        self.token = token or secrets.token_urlsafe(24)
        handler = type('MPCHandler', (Handler,), {'core': self.core, 'token': self.token, 'app': self})
        self.httpd = _Server(('127.0.0.1', port), handler)
        self.port = self.httpd.server_address[1]
        self.url = 'http://127.0.0.1:%d/?t=%s' % (self.port, self.token)
        self._last_seen = time.monotonic()
        self._seen_once = False
        self._done = threading.Event()
        self.stopping = self._done
        self._holds = 0
        self._held_once = False
        self._lock = threading.Lock()
        self.window = None

    def touch(self):
        self._last_seen = time.monotonic()
        self._seen_once = True

    def hold(self, change):
        with self._lock:
            self._holds += change
            if change > 0:
                self._held_once = True
            log.info('window %s (%d open)', 'connected' if change > 0 else 'connection closed', self._holds)
        self.touch()

    def window_closed(self):
        pass                                     # the held connection closing is what counts

    def serve(self):
        threading.Thread(target=self.httpd.serve_forever, name='mpc-http', daemon=True).start()
        self.core.start()

    def open_window(self):
        self.window = open_app_window(self.url)
        log.info('app window: %s', 'started' if self.window is not None else 'no Edge/Chrome')
        if self.window is None:
            log.info('no Edge/Chrome found: opening the default browser')
            webbrowser.open(self.url)

    def wait(self):
        """Return when the window is gone: its held connection closed and it stopped calling."""
        opened = time.monotonic()
        while not self._done.wait(0.5):
            # The page keeps one connection open (/api/hold) for as long as it lives and pings every
            # few seconds. The browser's launcher process is NOT a sign of life: Edge hands the window
            # to another process and the launcher exits at once. 0.1.0 trusted it and quit after six
            # quiet seconds with the window still open.
            now = time.monotonic()
            job = self.core.job
            if (job and job.state == 'running') or self._holds > 0:
                continue
            if not self._seen_once:
                if now - opened > 180:
                    log.info('the window never connected')
                    break
            elif now - self._last_seen > (self.quiet_after_hold if self._held_once else self.quiet_without_hold):
                log.info('window gone: quiet for %.0fs', now - self._last_seen)
                break

    def close(self):
        self._done.set()
        self.core.shutdown()
        self.httpd.shutdown()
        self.httpd.server_close()


def _browser_candidates():
    found = []
    try:
        import winreg
        for name in ('msedge.exe', 'chrome.exe'):
            for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                try:
                    with winreg.OpenKey(hive, r'SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths' + '\\' + name) as key:
                        found.append(winreg.QueryValueEx(key, '')[0])
                except OSError:
                    continue
    except ImportError:
        pass
    for root in (os.environ.get('ProgramFiles(x86)'), os.environ.get('ProgramFiles'),
                 os.environ.get('LOCALAPPDATA')):
        if root:
            found.append(os.path.join(root, 'Microsoft', 'Edge', 'Application', 'msedge.exe'))
            found.append(os.path.join(root, 'Google', 'Chrome', 'Application', 'chrome.exe'))
    seen = []
    for exe in found:
        if exe and os.path.isfile(exe) and exe.lower() not in [s.lower() for s in seen]:
            seen.append(exe)
    return sorted(seen, key=lambda e: 0 if 'msedge' in e.lower() else 1)


def open_app_window(url):
    """A chromeless browser window with its own profile folder, so its lifetime is ours to watch."""
    profile = str(paths.data_dir() / 'window')
    for exe in _browser_candidates():
        try:
            return subprocess.Popen([exe, '--app=' + url, '--user-data-dir=' + profile, '--no-first-run',
                                     '--no-default-browser-check', '--window-size=1480,920',
                                     '--disable-features=Translate',
                                     # keep the page's timers running while the window is behind osu!
                                     '--disable-background-timer-throttling', '--disable-renderer-backgrounding',
                                     '--disable-backgrounding-occluded-windows'],
                                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL)
        except OSError:
            continue
    return None


def _instance_file():
    return paths.data_dir() / 'instance.json'


def _existing_instance():
    """URL of a Map Pack Create that is already running for this user, if it answers."""
    try:
        info = json.loads(_instance_file().read_text(encoding='utf-8'))
        request = urllib.request.Request('http://127.0.0.1:%d/api/ping' % info['port'], data=b'{}', method='POST',
                                         headers={'X-MPC-Token': info['token'], 'Content-Type': 'application/json'})
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(request, timeout=2) as response:
            if response.status == 200:
                return 'http://127.0.0.1:%d/?t=%s' % (info['port'], info['token'])
    except Exception:
        pass
    return None


def main():
    logfile = paths.init_logging()
    log.info('%s %s starting, log %s', APP_NAME, __version__, logfile.name)
    existing = _existing_instance()
    if existing:
        log.info('already running: opening another window')
        if open_app_window(existing) is None:
            webbrowser.open(existing)
        return 0
    port = int(os.environ.get('MPC_PORT') or 0)
    app = App(port=port, token=os.environ.get('MPC_TOKEN') or None)
    try:
        paths.data_dir().mkdir(parents=True, exist_ok=True)
        _instance_file().write_text(json.dumps({'port': app.port, 'token': app.token, 'pid': os.getpid()}),
                                    encoding='utf-8')
    except OSError:
        pass
    app.serve()
    if os.environ.get('MPC_NO_WINDOW'):
        log.info('window suppressed; serving on port %d', app.port)
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            pass
    else:
        app.open_window()
        app.wait()
    app.close()
    try:
        _instance_file().unlink()
    except OSError:
        pass
    log.info('exiting')
    return 0


if __name__ == '__main__':
    sys.exit(main())
