"""Runs the share package the way someone who just received it would: unzipped somewhere else, fresh data.

    python tests/check_share.py           (uses output/Osu!Mania MPC v*.zip; the window opens on a hidden desktop)
Checks: it starts, finds ffmpeg.exe and the calculator next to/inside itself, the window connects,
an estimate comes back, and a small export lands in the packs folder beside the exe.
"""
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
PORT, TOKEN = 8797, 'share'
BASE = 'http://127.0.0.1:%d' % PORT
FAILED = []


def check(name, ok, detail=''):
    print(('ok   ' if ok else 'FAIL ') + name + (('  ' + str(detail)) if detail and not ok else ''))
    if not ok:
        FAILED.append(name)


def call(path, data=None):
    req = urllib.request.Request(BASE + path, data=data, headers={'X-MPC-Token': TOKEN, 'Content-Type': 'application/json'})
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=30) as res:
        return json.load(res)


def main():
    running = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq Osu!Mania MPC.exe'], capture_output=True, text=True)
    if 'Osu!Mania MPC.exe' in running.stdout:        # this test ends by closing every copy of the program
        sys.exit('Osu!Mania MPC is running. Close it first: this check would close it.')
    zips = glob.glob(os.path.join(ROOT, 'output', 'Osu!Mania MPC v*.zip'))
    check('one share zip in output', len(zips) == 1, zips)
    if len(zips) != 1:
        return
    work = tempfile.mkdtemp(prefix='mpc-share-')
    zipfile.ZipFile(zips[0]).extractall(work)
    folder = os.path.join(work, 'Osu!Mania MPC')
    names = sorted(os.listdir(folder))
    check('zip holds the program, ffmpeg, the guide and the licences',
          names == ['Osu!Mania MPC.exe', 'README.txt', 'ffmpeg.exe', 'licenses'], names)
    env = dict(os.environ, MPC_DATA_DIR=os.path.join(work, 'data'), MPC_PORT=str(PORT), MPC_TOKEN=TOKEN)
    for key in ('MPC_PACKS_DIR', 'MPC_FFMPEG', 'MPC_CALC'):
        env.pop(key, None)
    runner = subprocess.Popen([sys.executable, os.path.join(ROOT, 'tests', 'run_hidden.py'), '150',
                               os.path.join(folder, 'Osu!Mania MPC.exe')], env=env,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        state = None
        for _ in range(240):
            try:
                state = call('/api/state')
                if state['library']['status'] in ('ready', 'error'):
                    break
            except OSError:
                pass
            time.sleep(0.5)
        check('starts and reads the osu! library', bool(state) and state['library']['status'] == 'ready',
              state and state['library'])
        if not state or state['library']['status'] != 'ready':
            return
        check('finds ffmpeg and the calculator on its own', state['tools'] == {'ffmpeg': True, 'calc': True}, state['tools'])
        check('starts empty for a new user', state['project'] == {}, state['project'])
        check('exports go beside the exe', os.path.normcase(state['packsDir']) == os.path.normcase(os.path.join(folder, 'packs')),
              state['packsDir'])
        row = call('/api/search?q=&keys=4')['rows'][5]
        rating = call('/api/rating?md5=%s&rate=1.1' % row['md5'])['rating']
        check('difficulty estimate works', bool(rating and rating['msd']), rating)
        body = {'pack': {'title': 'Share Test', 'creator': 'F', 'tags': 'x'}, 'dest': 'packs',
                'entries': [{'uid': 'a', 'md5': row['md5'], 'rate': 1.1, 'followPitch': False, 'version': 'A'}],
                'delete': {'enabled': True, 'preview': {'mode': 'none'}}}
        plan = call('/api/export/begin', json.dumps(body).encode())
        check('export begins', plan.get('ok'), plan)
        if plan.get('ok'):
            call('/api/export/run', json.dumps({'job': plan['job']}).encode())
            status = {}
            for _ in range(300):
                status = call('/api/export/status')
                if status['state'] != 'running':
                    break
                time.sleep(0.4)
            files = sorted(os.listdir(plan['folder'])) if status.get('state') == 'done' else []
            check('export finishes', status.get('state') == 'done' and 'audio01.mp3' in files and 'delete.mp3' in files,
                  (status.get('error'), files))
        log = ''.join(open(p, encoding='utf-8').read() for p in glob.glob(os.path.join(work, 'data', 'logs', '*.log')))
        check('the window connected', 'window connected' in log, log[-300:])
    finally:
        subprocess.run(['taskkill', '/IM', 'Osu!Mania MPC.exe', '/F'], capture_output=True)
        subprocess.run(['powershell', '-NoProfile', '-Command',
                        "Get-CimInstance Win32_Process -Filter \"name='msedge.exe'\" | Where-Object { $_.CommandLine -like '*"
                        + os.path.basename(work) + "*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"],
                       capture_output=True)
        runner.kill()
        time.sleep(2)
        shutil.rmtree(work, ignore_errors=True)


if __name__ == '__main__':
    main()
    print('\n%s' % ('ALL OK' if not FAILED else 'FAILED: ' + ', '.join(FAILED)))
    sys.exit(1 if FAILED else 0)
