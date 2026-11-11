"""The rate changer's export: new difficulties next to the original, the original files never touched.

usage: python tests/test_rate.py     (copies one real map into a temporary Songs folder and works there;
                                      the osu! folder itself is only read)
"""
import hashlib
import os
import shutil
import sys
import tempfile
import time

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, os.path.join(ROOT, 'src'))
TEMP = tempfile.mkdtemp(prefix='mpc-ratetest-')
os.environ['MPC_DATA_DIR'] = os.path.join(TEMP, 'data')
os.environ['MPC_PACKS_DIR'] = os.path.join(TEMP, 'packs')

from mpc import osufile  # noqa: E402
from mpc.core import Core, ExportError  # noqa: E402
from mpc.osudb import Library  # noqa: E402

FAILED = []


def check(name, ok, detail=''):
    print(('ok   ' if ok else 'FAIL ') + name + (('  ' + str(detail)) if detail and not ok else ''))
    if not ok:
        FAILED.append(name)


def digest(folder):
    out = {}
    for name in sorted(os.listdir(folder)):
        with open(os.path.join(folder, name), 'rb') as f:
            out[name] = hashlib.md5(f.read()).hexdigest()
    return out


def run(core, project):
    plan = core.export_begin(project)
    for image in plan['images']:
        assert core.export_image(plan['job'], image['name'], b'\xff\xd8fake'), image
    assert core.export_run(plan['job'])
    began = time.time()
    while core.export_status()['state'] == 'running' and time.time() - began < 300:
        time.sleep(0.2)
    return plan, core.export_status()


def main():
    real = Library()
    real.load(os.path.join(os.environ['LOCALAPPDATA'], 'osu!'))
    pick = None
    for e in real.entries:
        if e['keys'] == 4 and 60000 < e['total_ms'] < 120000 and e['audio'].lower().endswith('.ogg'):
            info = osufile.info(e['path'])
            if osufile.audio_path(e['path'], info['audio']) and osufile.background_path(e['path'], info['background']):
                pick = (e, info)
                break
    check('found an ogg map with a background', bool(pick))
    if not pick:
        return
    entry, info = pick
    songs = os.path.join(TEMP, 'Songs')
    folder = os.path.join(songs, 'copy')
    os.makedirs(folder)
    for path in (entry['path'], osufile.audio_path(entry['path'], info['audio']),
                 osufile.background_path(entry['path'], info['background'])):
        shutil.copy2(path, folder)

    core = Core()
    lib = Library()
    lib.songs, lib.status = songs, 'ready'
    lib.adopt('copy')
    core.library = lib
    md5 = lib.entries[0]['md5']
    before = digest(folder)

    project = {'mode': 'rate', 'md5': md5, 'dest': 'source', 'bitrate': 192, 'entries': [
        {'uid': 'r100', 'rate': 1.0, 'version': info['version'], 'image': True},         # name taken: must change
        {'uid': 'r110', 'rate': 1.1, 'version': info['version'] + ' 1.1x', 'followPitch': False, 'image': True},
        {'uid': 'r120', 'rate': 1.2, 'version': '1.2x', 'followPitch': True, 'image': False},
    ]}
    try:
        core.export_begin(dict(project, entries=[]))
        check('no rates refused', False)
    except ExportError:
        check('no rates refused', True)

    # cancelled before it starts: the picture that already arrived is removed, nothing else changes
    plan = core.export_begin(project)
    check('works in the map folder', os.path.samefile(plan['folder'], folder), plan['folder'])
    check('only wanted pictures are asked for', len(plan['images']) == 2, plan['images'])
    core.export_image(plan['job'], plan['images'][0]['name'], b'x')
    check('unknown picture name refused', not core.export_image(plan['job'], os.path.basename(entry['path']), b'x'))
    core.export_cancel()
    check('cancel removes only what was written', digest(folder) == before, sorted(set(digest(folder)) - set(before)))

    plan, status = run(core, project)
    check('finished', status['state'] == 'done', status.get('error'))
    after = digest(folder)
    check('original files untouched', all(after.get(k) == v for k, v in before.items()))
    new = sorted(set(after) - set(before))
    print('     ' + '\n     '.join(new))
    charts = [n for n in new if n.endswith('.osu')]
    check('3 new charts, 2 new audio files, 2 pictures', (len(charts), len([n for n in new if n.endswith('.mp3')]),
                                                       len([n for n in new if n.endswith('.jpg')])) == (3, 2, 2), new)
    by_version = {osufile.info(os.path.join(folder, n))['version']: osufile.info(os.path.join(folder, n)) for n in charts}
    check('taken name got a suffix', info['version'] + ' (2)' in by_version, list(by_version))
    same = by_version.get(info['version'] + ' (2)')
    check('1.00x keeps the original audio', bool(same) and same['audio'] == info['audio'] and same['last_ms'] == info['last_ms'])
    fast = by_version.get('1.2x')
    check('1.20x: own audio, original picture, title kept, ids reset', bool(fast) and fast['audio'].endswith('_1.20x_pitch.mp3')
          and fast['background'] == info['background'] and fast['title'] == info['title'] and fast['set_id'] == -1
          and abs(fast['last_ms'] - info['last_ms'] / 1.2) <= 1, fast)
    mid = by_version.get(info['version'] + ' 1.1x')
    check('1.10x: its own picture', bool(mid) and mid['background'].endswith('_1.10x.jpg') and mid['background'] in new, mid)
    check('reports', [i['report']['mode'] for i in status['items']] == ['keep', 'stretch', 'resample'],
          [i['report'] for i in status['items']])

    # a second run must not overwrite the first run's files
    plan2, status2 = run(core, project)
    after2 = digest(folder)
    check('second run adds, never replaces', status2['state'] == 'done' and all(after2.get(k) == v for k, v in after.items())
          and len(after2) > len(after), status2.get('error'))

    # a folder of its own
    plan3, status3 = run(core, dict(project, dest='packs'))
    files = sorted(os.listdir(plan3['folder'])) if status3['state'] == 'done' else []
    print('     ' + '\n     '.join(files))
    check('own folder: charts, audio for every rate, original picture copied', status3['state'] == 'done'
          and len([f for f in files if f.endswith('.osu')]) == 3 and len([f for f in files if f.endswith('.mp3')]) == 3
          and os.path.basename(info['background']) in files, (status3.get('error'), files))
    check('own folder is under packs', os.path.dirname(plan3['folder']) == os.environ['MPC_PACKS_DIR'])
    check('map folder unchanged by it', digest(folder) == after2)
    core.shutdown()


if __name__ == '__main__':
    main()
    print('\n%s' % ('ALL OK' if not FAILED else 'FAILED: ' + ', '.join(FAILED)))
    sys.exit(1 if FAILED else 0)
