"""The parts the first build got wrong or lacked: when the program decides to exit, and following osu!.

usage: python tests/test_app.py      (no osu! needed: a stand-in process plays its part)
"""
import http.client
import json
import os
import subprocess
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'src'))
TEMP = tempfile.mkdtemp(prefix='mpc-apptest-')
os.environ['MPC_DATA_DIR'] = os.path.join(TEMP, 'data')
os.environ['MPC_PACKS_DIR'] = os.path.join(TEMP, 'packs')

from mpc import live  # noqa: E402
from mpc.core import Core  # noqa: E402
from mpc.osudb import Library  # noqa: E402
from mpc.server import App  # noqa: E402

FAILED = []
CHART = '''osu file format v14

[General]
AudioFilename: a.mp3
Mode: 3

[Metadata]
Title:New Song
Artist:Someone
Creator:Mapper
Version:Fresh

[Difficulty]
CircleSize:4
OverallDifficulty:8

[Events]

[TimingPoints]
0,500,4,2,0,50,1,0

[HitObjects]
64,192,1000,1,0,0:0:0:0:
448,192,2000,1,0,0:0:0:0:
'''


def check(name, ok, detail=''):
    print(('ok   ' if ok else 'FAIL ') + name + (('  ' + str(detail)) if detail and not ok else ''))
    if not ok:
        FAILED.append(name)


class Gone:
    """The browser launcher process, already exited: what Edge does on the owner's PC."""

    def poll(self):
        return 0


def get(app, path):
    conn = http.client.HTTPConnection('127.0.0.1', app.port, timeout=5)
    conn.request('GET', path, headers={'X-MPC-Token': app.token})
    res = conn.getresponse()
    body = res.read()
    conn.close()
    return res.status, body


def test_lifetime():
    core = Core()
    core.library.status = 'ready'                       # no library needed here
    core.start = lambda: None
    app = App(core=core)
    app.quiet_after_hold = 3
    app.serve()
    app.window = Gone()
    ended = threading.Event()
    threading.Thread(target=lambda: (app.wait(), ended.set()), daemon=True).start()

    status, _ = get(app, '/api/state')
    check('api answers', status == 200, status)
    hold = http.client.HTTPConnection('127.0.0.1', app.port, timeout=10)
    hold.request('GET', '/api/hold?t=' + app.token)
    res = hold.getresponse()
    check('hold connection opens', res.status == 200, res.status)
    check('hold streams', res.read(1) == b'.')
    time.sleep(9)                                       # 0.1.0 quit here: launcher gone + 6 quiet seconds
    check('still running while the window holds its connection', not ended.is_set())
    status, body = get(app, '/api/map?md5=' + '0' * 32)
    check('still answering', status == 404 and b'not found' in body, (status, body))
    res.close()                                         # the response owns the socket: close both
    hold.close()
    began = time.time()
    check('exits after the window is gone', ended.wait(15), 'did not exit')
    print('     exit %.1fs after the connection closed' % (time.time() - began))
    app.close()


def test_live():
    songs = os.path.join(TEMP, 'Songs')
    folder = os.path.join(songs, '123 Someone - New Song')
    os.makedirs(folder)
    with open(os.path.join(folder, 'Someone - New Song (Mapper) [Fresh].osu'), 'w', encoding='utf-8') as f:
        f.write(CHART)
    import hashlib
    md5 = hashlib.md5(open(os.path.join(folder, 'Someone - New Song (Mapper) [Fresh].osu'), 'rb').read()).hexdigest()

    fake = subprocess.Popen([sys.executable, os.path.join(HERE, 'fake_osu.py'), 'f' * 32], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, text=True)
    pid = int(fake.stdout.readline())

    def say(line):
        fake.stdin.write(line + '\n')
        fake.stdin.flush()
        fake.stdout.readline()

    core = Core()
    lib = Library()
    lib.songs, lib.status = songs, 'ready'
    core.library = lib
    pids = [pid]
    core.watcher = live.LiveWatcher(interval=0.1, pids=lambda: list(pids), require_32bit=False)
    core.watcher.start()

    def wait_for(fn, seconds=8):
        end = time.time() + seconds
        while time.time() < end:
            state = core.live_state()
            if fn(state):
                return state
            time.sleep(0.1)
        return core.live_state()

    state = wait_for(lambda s: s['readable'] and s['md5'])
    check('reads the selected md5', state['md5'] == 'f' * 32 and state['running'], state)
    check('a map that is not in the library is not offered', state['known'] is False, state)
    say('file 123 Someone - New Song|Someone - New Song (Mapper) [Fresh].osu')
    say('md5 ' + md5)
    state = wait_for(lambda s: s['md5'] == md5 and s['known'])
    check('a map osu!.db does not list yet is read from its folder', state['known'] is True, state)
    detail = core.map_detail(md5)
    check('and can be opened', bool(detail and detail['title'] == 'New Song' and detail['keys'] == 4), detail)
    say('file ..|evil.osu')
    say('md5 ' + 'e' * 32)
    state = wait_for(lambda s: s['md5'] == 'e' * 32)
    check('a folder outside Songs is ignored', state['known'] is False, state)
    say('state 2')
    state = wait_for(lambda s: s['label'] == '플레이 중')
    check('screen label', state['label'] == '플레이 중', state)
    say('none')
    state = wait_for(lambda s: s['md5'] is None)
    check('no selection', state['md5'] is None and state['readable'], state)
    fake.stdin.write('quit\n')
    fake.stdin.flush()
    fake.wait(timeout=5)
    pids.clear()
    state = wait_for(lambda s: not s['running'])
    check('osu! closed', state['running'] is False, state)
    core.shutdown()


if __name__ == '__main__':
    test_lifetime()
    test_live()
    print('\n%s' % ('ALL OK' if not FAILED else 'FAILED: ' + ', '.join(FAILED)))
    sys.exit(1 if FAILED else 0)
