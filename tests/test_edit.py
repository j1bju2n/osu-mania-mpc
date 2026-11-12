"""Rebuilding an uploaded set (online ids kept) and saved packs.

usage: python tests/test_edit.py     (builds a pretend uploaded set from real maps inside a temporary Songs
                                      folder and works there; the osu! folder itself is only read)
"""
import hashlib
import os
import shutil
import sys
import tempfile
import time
import zipfile

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, os.path.join(ROOT, 'src'))
TEMP = tempfile.mkdtemp(prefix='mpc-edittest-')
os.environ['MPC_DATA_DIR'] = os.path.join(TEMP, 'data')
os.environ['MPC_PACKS_DIR'] = os.path.join(TEMP, 'packs')
os.environ['MPC_SAVE_DIR'] = os.path.join(TEMP, 'save')

from mpc import osufile  # noqa: E402
from mpc.core import Core, ExportError  # noqa: E402
from mpc.osudb import Library  # noqa: E402

FAILED = []
SET_ID = 1234567


def check(name, ok, detail=''):
    print(('ok   ' if ok else 'FAIL ') + name + (('  ' + str(detail)) if detail and not ok else ''))
    if not ok:
        FAILED.append(name)


def digest(folder):
    out = {}
    for base, _dirs, files in os.walk(folder):
        for name in files:
            path = os.path.join(base, name)
            with open(path, 'rb') as f:
                out[os.path.relpath(path, folder)] = hashlib.md5(f.read()).hexdigest()
    return out


def run(core, project):
    plan = core.export_begin(project)
    for image in plan['images']:
        assert core.export_image(plan['job'], image['name'], b'\xff\xd8new ' + image['name'].encode()), image
    if plan['deleteImage']:
        assert core.export_image(plan['job'], plan['deleteImage'], b'\xff\xd8delete')
    assert core.export_run(plan['job'])
    began = time.time()
    while core.export_status()['state'] == 'running' and time.time() - began < 300:
        time.sleep(0.2)
    return plan, core.export_status()


def build_set(songs):
    """Three different songs as one uploaded set, plus a [delete] difficulty, a hitsound and a stray file."""
    real = Library()
    real.load(os.path.join(os.environ['LOCALAPPDATA'], 'osu!'))
    picks, seen = [], set()
    for e in real.entries:
        if e['keys'] != 4 or not 45000 < e['total_ms'] < 110000 or e['folder'] in seen:
            continue
        info = osufile.info(e['path'])
        sound, picture = osufile.audio_path(e['path'], info['audio']), osufile.background_path(e['path'], info['background'])
        if sound and picture and sound.lower().endswith(('.mp3', '.ogg')) and '/' not in info['audio'] and '\\' not in info['audio']:
            picks.append((e, info, sound, picture))
            seen.add(e['folder'])
        if len(picks) == 4:
            break
    if len(picks) < 4:
        return None
    folder = os.path.join(songs, '%d Various Artists - Old Pack' % SET_ID)
    os.makedirs(os.path.join(folder, 'sb'))
    meta = {'Title': 'Old Pack', 'TitleUnicode': 'Old Pack', 'Artist': 'Various Artists', 'ArtistUnicode': 'Various Artists',
            'Creator': 'Tester', 'Source': '', 'Tags': 'old tags'}
    made = []
    for i, (e, info, sound, picture) in enumerate(picks[:3]):
        audio_name = 'audio%02d%s' % (i + 1, os.path.splitext(sound)[1].lower())
        bg_name = 'bg%02d%s' % (i + 1, os.path.splitext(picture)[1].lower())
        shutil.copyfile(sound, os.path.join(folder, audio_name))
        shutil.copyfile(picture, os.path.join(folder, bg_name))
        text = osufile.transform(osufile.read(e['path']), audio_name=audio_name, background_name=bg_name,
                                 meta=dict(meta, Version='Old %d' % (i + 1)), ids=(1001 + i, SET_ID))
        name = 'Various Artists - Old Pack (Tester) [Old %d].osu' % (i + 1)
        with open(os.path.join(folder, name), 'w', encoding='utf-8', newline='') as f:
            f.write(text)
        made.append(name)
    with open(os.path.join(folder, 'Various Artists - Old Pack (Tester) [delete].osu'), 'w', encoding='utf-8', newline='') as f:
        f.write(osufile.delete_difficulty(dict(meta, Version='delete'), 'delete.mp3', 'bg01' + os.path.splitext(picks[0][3])[1].lower(),
                                          4, 601000, 300000, ids=(1000, SET_ID)))
    shutil.copyfile(picks[0][2], os.path.join(folder, 'delete.mp3'))       # stands in for the silent audio
    for name in ('soft-hitnormal.wav', os.path.join('sb', 'flash.png'), 'notes.txt'):
        with open(os.path.join(folder, name), 'wb') as f:
            f.write(b'x' * 64)
    extra = os.path.join(songs, 'other song')                               # the map that will be swapped in
    os.makedirs(extra)
    e, info, sound, picture = picks[3]
    for path in (e['path'], sound, picture):
        shutil.copy2(path, extra)
    return folder, made


def main():
    songs = os.path.join(TEMP, 'Songs')
    built = build_set(songs)
    check('built a pretend uploaded set from real maps', bool(built))
    if not built:
        return
    folder, made = built
    core = Core()
    lib = Library()
    lib.songs, lib.status = songs, 'ready'
    lib.adopt(os.path.basename(folder))
    lib.adopt('other song')
    core.library = lib
    by_version = {e['version']: e for e in lib.entries}
    other = next(e for e in lib.entries if e['folder'] == 'other song')
    before = digest(folder)

    found = core.set_detail(by_version['Old 1']['md5'])
    check('set read: id, four difficulties, one of them the delete one', found['setId'] == SET_ID and len(found['slots']) == 4
          and [s['kind'] for s in found['slots']].count('delete') == 1 and found['audios'] == 4, found)
    check('set read: ids per difficulty, no full paths handed out', sorted(s['id'] for s in found['slots']) == [1000, 1001, 1002, 1003]
          and 'path' not in found and all('path' not in s for s in found['slots']))
    check('set read: other files counted', found['others'] == 3, found['others'])

    pack = {'title': 'New Pack', 'artist': 'Various Artists', 'creator': 'Tester', 'source': '', 'tags': 'new tags', 'resetIds': True}
    project = {
        'mode': 'edit', 'pack': pack, 'bitrate': 192, 'imageFormat': 'jpg', 'osz': True, 'dest': 'songs',
        'edit': {'folder': os.path.basename(folder), 'setId': SET_ID, 'thumbs': True, 'unify': True, 'deleteSlot': 1000, 'carry': []},
        'entries': [
            {'uid': 'a', 'md5': by_version['Old 1']['md5'], 'rate': 1.0, 'version': 'Old 1', 'slot': 1001},        # as it is
            {'uid': 'b', 'md5': other['md5'], 'rate': 1.1, 'followPitch': True, 'version': 'Swapped', 'slot': 1002},  # replaced
            {'uid': 'c', 'md5': by_version['Old 3']['md5'], 'rate': 1.2, 'followPitch': True, 'version': 'Old 3 fast', 'slot': 0},  # new
        ],
        'delete': {'enabled': True, 'name': 'delete', 'minutes': 5, 'preview': {'mode': 'none'}},
    }
    for bad, label in ((dict(project, edit=dict(project['edit'], setId=5)), 'another set id refused'),
                       (dict(project, edit=dict(project['edit'], folder='..')), 'folder outside Songs refused'),
                       (dict(project, entries=[dict(project['entries'][0], slot=999)]), 'unknown BeatmapID refused'),
                       (dict(project, entries=[dict(project['entries'][0]), dict(project['entries'][1], slot=1001)]),
                        'one BeatmapID for two difficulties refused')):
        try:
            core.export_begin(bad)
            core.export_cancel()
            check(label, False)
        except ExportError:
            check(label, True)

    plan, status = run(core, project)
    check('finished', status['state'] == 'done', status.get('error'))
    out = plan['folder']
    check('made beside the program, never in Songs', os.path.dirname(out) == os.environ['MPC_PACKS_DIR'], out)
    check('folder keeps the set id in front', os.path.basename(out).startswith('%d ' % SET_ID), out)
    check('original folder untouched', digest(folder) == before)
    files = digest(out)
    print('     ' + '\n     '.join(sorted(files)))
    charts = {n: osufile.info(os.path.join(out, n)) for n in files if n.endswith('.osu')}
    ids = {c['version']: (c['beatmap_id'], c['set_id']) for c in charts.values()}
    check('ids: kept, taken over, new (0), delete', ids == {'Old 1': (1001, SET_ID), 'Swapped': (1002, SET_ID),
                                                          'Old 3 fast': (0, SET_ID), 'delete': (1000, SET_ID)}, ids)
    check('metadata the same in every difficulty', all((c['title'], c['artist'], c['creator'], c['tags']) ==
                                                      ('New Pack', 'Various Artists', 'Tester', 'new tags') for c in charts.values()),
          [(c['title'], c['tags']) for c in charts.values()])

    same_name = made[0]
    check('untouched difficulty keeps its file name', same_name in files, sorted(files))
    old_lines = osufile.read(os.path.join(folder, same_name)).splitlines()
    new_lines = osufile.read(os.path.join(out, same_name)).splitlines()
    changed = [(a, b) for a, b in zip(old_lines, new_lines) if a != b]
    keys = sorted({b.partition(':')[0] if not b.startswith('0,0,') else 'bg' for a, b in changed})
    check('untouched difficulty: only title/tags/picture lines differ', len(old_lines) == len(new_lines)
          and keys == ['Tags', 'Title', 'TitleUnicode', 'bg'], keys)
    kept = charts[same_name]
    check('untouched difficulty: its own audio, byte for byte', files.get(kept['audio']) == before.get(kept['audio']))
    check('untouched difficulty: a new picture', kept['background'] in files and kept['background'] not in before
          or files.get(kept['background']) != before.get(kept['background']), kept['background'])
    swapped = next(c for c in charts.values() if c['version'] == 'Swapped')
    check('replaced difficulty: its own new audio and picture', swapped['audio'] in files and swapped['background'] in files
          and files[swapped['audio']] not in before.values() and files[swapped['background']] not in before.values(), swapped)
    check('file of the removed difficulty is not there', made[1] not in files and made[2] not in files)
    check('hitsound and storyboard file carried over, stray text file left out', 'soft-hitnormal.wav' in files
          and os.path.join('sb', 'flash.png') in files and 'notes.txt' not in files, sorted(files))
    check('audio of replaced difficulties not carried over', 'audio02.mp3' not in files and 'audio02.ogg' not in files
          or files.get('audio02.mp3') != before.get('audio02.mp3'))
    info = status['edit']
    check('report: removed difficulty named', [r['id'] for r in info['removed']] == [1003] and info['skipped'] == 1, info)
    check('report: how each difficulty was made', {r['version']: r['how'] for r in info['rows']} ==
          {'Old 1': 'asis', 'Swapped': 'made', 'Old 3 fast': 'made', 'delete': 'delete'}, info['rows'])
    check('osz holds the folder, sub folder included', bool(status['osz']) and os.path.isfile(status['osz'])
          and 'sb/flash.png' in zipfile.ZipFile(status['osz']).namelist())

    # thumbnails only: nothing but the picture and its line may change
    plain = dict(project, osz=False, edit=dict(project['edit'], thumbs=True, unify=False),
                 entries=[{'uid': str(i), 'md5': by_version['Old %d' % i]['md5'], 'rate': 1.0, 'version': 'Old %d' % i,
                           'slot': 1000 + i} for i in (1, 2, 3)])
    plan2, status2 = run(core, plain)
    out2 = plan2['folder']
    check('thumbnails only: finished', status2['state'] == 'done', status2.get('error'))
    ok = True
    for name in made:
        a = osufile.read(os.path.join(folder, name)).splitlines()
        b = osufile.read(os.path.join(out2, name)).splitlines()
        diff = [(x, y) for x, y in zip(a, b) if x != y]
        picture = osufile.info(os.path.join(out2, name))['background']
        ok = (ok and len(a) == len(b) and len(diff) <= 1 and all(y.startswith('0,0,"bg') for x, y in diff)
              and digest(out2)[picture] not in before.values())
    check('thumbnails only: at most the picture line differs, the picture itself is new', ok)
    check('thumbnails only: nothing left out, no audio converted', status2['edit']['removed'] == []
          and all(i['report']['mode'] == 'keep' for i in status2['items']), status2['edit'])

    # pictures left alone as well: a pure copy with the same ids
    plan3, status3 = run(core, dict(plain, edit=dict(plain['edit'], thumbs=False)))
    check('nothing changed: no pictures asked for, files equal the originals', status3['state'] == 'done'
          and plan3['images'] == [] and all(digest(plan3['folder']).get(n) == before[n] for n in made + ['bg01' + os.path.splitext(charts[same_name]['background'])[1]] if n in before),
          status3.get('error'))

    # ---- saved packs
    asset = core.store_asset('pic.png', b'\x89PNG pretend picture')
    core.save_settings({'customSymbols': [{'asset': asset, 'name': 'mydan+'}]})
    saved = {'v': 2, 'pack': {'title': 'Saved Pack'}, 'rc': {'md5': 'x'}, 'thumb': {'layers': [{'type': 'symbol', 'src': 'asset:' + asset}]},
             'entries': [{'uid': 'a', 'md5': other['md5'], 'rate': 1.1, 'meta': {'title': 't'}},
                         {'uid': 'b', 'md5': 'f' * 32, 'rate': 1.0, 'meta': {'title': 'gone'}}]}
    res = core.save_write('My: Pack?', saved)
    check('save written with a usable file name', res['ok'] and res['name'] == 'My Pack' and os.path.isfile(res['file']), res)
    check('save lists', [(r['name'], r['maps'], r['title']) for r in core.save_list()['saves']] == [('My Pack', 2, 'Saved Pack')],
          core.save_list())
    check('save exists', core.save_exists('My Pack') and not core.save_exists('nothing'))
    with zipfile.ZipFile(res['file']) as z:
        names = z.namelist()
    check('save carries the picture it uses, not the rate changer', 'assets/' + asset in names
          and 'rc' not in __import__('json').loads(zipfile.ZipFile(res['file']).read('project.json')), names)
    os.remove(core.asset_path(asset))                     # as on another PC: the picture and the symbol are not there
    core.save_settings({'customSymbols': []})
    back = core.save_read('My Pack')
    check('save read: project, picture and symbol restored', back['ok'] and back['project']['pack']['title'] == 'Saved Pack'
          and bool(core.asset_path(asset)) and [s['name'] for s in back['symbols']] == ['mydan+'], back)
    check('save read: the map this osu! does not have is named', back['missing'] == ['f' * 32], back.get('missing'))
    check('missing check on its own', core.missing([other['md5'], 'e' * 32]) == ['e' * 32])
    check('unreadable save refused', not core.save_read('nothing')['ok'])
    check('save deleted', core.save_delete('My Pack') and core.save_list()['saves'] == [])
    core.shutdown()


if __name__ == '__main__':
    try:
        main()
    finally:
        shutil.rmtree(TEMP, ignore_errors=True)
    print('\n%s' % ('ALL OK' if not FAILED else 'FAILED: ' + ', '.join(FAILED)))
    sys.exit(1 if FAILED else 0)
