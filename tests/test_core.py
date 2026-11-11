"""Core checks without the interface: .osu transform rules, the library, and one real export.

usage: python tests/test_core.py            (uses the osu! folder on this PC, read-only;
                                             writes only to a temporary folder)
"""
import json
import os
import sys
import tempfile
import time

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, os.path.join(ROOT, 'src'))
TEMP = tempfile.mkdtemp(prefix='mpc-test-')
os.environ['MPC_DATA_DIR'] = os.path.join(TEMP, 'data')
os.environ['MPC_PACKS_DIR'] = os.path.join(TEMP, 'packs')

from mpc import audio, osufile  # noqa: E402
from mpc.core import Core, ExportError  # noqa: E402

FAILED = []


def check(name, ok, detail=''):
    print(('ok   ' if ok else 'FAIL ') + name + (('  ' + str(detail)) if detail and not ok else ''))
    if not ok:
        FAILED.append(name)


SAMPLE = '''osu file format v14

[General]
AudioFilename: song.ogg
AudioLeadIn: 0
PreviewTime: 30000
Mode: 3

[Editor]
Bookmarks: 1000,3000

[Metadata]
Title:Song
TitleUnicode:노래
Artist:Someone
ArtistUnicode:누군가
Creator:Mapper
Version:Hard
Source:
Tags:a b
BeatmapID:123
BeatmapSetID:456

[Difficulty]
HPDrainRate:7
CircleSize:4
OverallDifficulty:8
ApproachRate:5
SliderMultiplier:1.4
SliderTickRate:1

[Events]
//Background and Video events
Video,0,"v.mp4"
0,0,"my bg, final.jpg",0,0
//Break Periods
2,10000,20000
Sprite,Background,Centre,"sb.png",320,240
 F,0,0,1000,0,1

[TimingPoints]
1000,500,4,2,0,50,1,0
1000,-80,4,2,0,50,0,0
61000,400,4,2,0,50,1,1

[HitObjects]
64,192,1000,1,0,0:0:0:0:
192,192,1250,128,0,2250:0:0:0:0:
448,192,61000,1,0,0:0:0:0:
'''


def test_transform():
    info = osufile.info_from_text(SAMPLE)
    check('info: keys/notes/lns', (info['keys'], info['notes'], info['lns']) == (4, 3, 1), info)
    check('info: background with comma', info['background'] == 'my bg, final.jpg', info['background'])
    check('info: bpm', info['bpm'] == 120.0, info['bpm'])
    meta = {'Title': 'Pack', 'TitleUnicode': 'Pack', 'Artist': 'V.A.', 'ArtistUnicode': 'V.A.', 'Creator': 'Me',
            'Version': 'Song [1.25x]', 'Source': '', 'Tags': 'x y z'}
    out = osufile.transform(SAMPLE, rate=1.25, audio_name='audio01.mp3', background_name='bg01.jpg', meta=meta,
                            od=8.5, hp=None, reset_ids=True)
    lines = out.split('\r\n')
    check('transform: CRLF only', '\n' not in out.replace('\r\n', ''))
    for expected in ('AudioFilename: audio01.mp3', 'PreviewTime: 24000', 'Bookmarks: 800,2400', 'Title:Pack',
                     'Version:Song [1.25x]', 'Tags:x y z', 'BeatmapID:0', 'BeatmapSetID:-1',
                     'OverallDifficulty:8.5', 'HPDrainRate:7', '0,0,"bg01.jpg",0,0', '2,8000,16000',
                     '800,400,4,2,0,50,1,0', '800,-80,4,2,0,50,0,0', '48800,320,4,2,0,50,1,1',
                     '64,192,800,1,0,0:0:0:0:', '192,192,1000,128,0,1800:0:0:0:0:', '448,192,48800,1,0,0:0:0:0:'):
        check('transform: ' + expected, expected in lines)
    check('transform: storyboard and video dropped', 'Sprite,' not in out and 'Video,' not in out and ' F,0' not in out)
    same = osufile.transform(SAMPLE, rate=1.0, audio_name='a.mp3', background_name='b.jpg', meta=meta,
                             reset_ids=False)
    check('transform 1.0x: notes untouched', '192,192,1250,128,0,2250:0:0:0:0:' in same and 'BeatmapID:123' in same)
    d = osufile.delete_difficulty(dict(meta, Version='delete'), 'delete.mp3', 'delete.jpg', 4, 601000, 300000)
    check('delete: notes and preview', '448,192,601000,1,0,0:0:0:0:' in d and 'PreviewTime: 300000' in d
          and 'Version:delete' in d and 'Mode: 3' in d)


def test_lag_estimator():
    import random
    rng = random.Random(3)
    ref = [0.0] * 60000
    for _ in range(700):
        ref[rng.randrange(100, 59900)] = rng.uniform(0.5, 3.0)
    for shift in (-9, 0, 4):
        test = [0.0] * 60000
        for i, v in enumerate(ref):
            if v and 0 <= i + shift < 60000:
                test[i + shift] = v
        lag, spread, used = audio.measure_lag(ref, test)
        check('lag estimator: %+d ms' % shift, used >= 5 and abs(lag - shift) < 0.05, (lag, spread, used))


def test_real_export():
    core = Core()
    core.library.load(core.settings.get('osuFolder') or os.path.join(os.environ['LOCALAPPDATA'], 'osu!'))
    lib = core.library
    check('library loaded', lib.status == 'ready' and len(lib.entries) > 0, lib.message)
    if lib.status != 'ready':
        return
    print('     %d mania difficulties, %d read from folders, player %r' % (len(lib.entries), lib.extra, lib.player))
    picks = []
    seen_ext = set()
    for e in lib.entries:
        if e['keys'] != 4 or not 60000 < e['total_ms'] < 150000:
            continue
        ext = os.path.splitext(e['audio'])[1].lower()
        if ext in seen_ext or ext not in ('.mp3', '.ogg') or not os.path.isfile(e['path']):
            continue
        if not osufile.audio_path(e['path']):
            continue
        seen_ext.add(ext)
        picks.append(e)
        if len(picks) == 2:
            break
    check('found an mp3 and an ogg map', len(picks) == 2)
    if len(picks) < 2:
        return
    detail = core.map_detail(picks[0]['md5'])
    check('map detail', bool(detail and detail['hasAudio'] and detail['lengthMs'] > 0), detail)
    rating = core.rating(picks[0]['md5'], 1.2)
    check('rating at 1.20x', bool(rating and rating['msd']), rating)
    print('     %s [%s] 1.20x -> msd %s, %s' % (detail['title'], detail['version'], rating and rating['msd'],
                                               rating and rating['dan']))
    project = {
        'pack': {'title': 'Test Pack', 'artist': 'V.A.', 'creator': 'Tester', 'tags': 'test  pack', 'resetIds': True,
                 'od': 8},
        'entries': [
            {'uid': 'a', 'md5': picks[0]['md5'], 'rate': 1.0, 'followPitch': False, 'version': 'One [1.00x]'},
            {'uid': 'b', 'md5': picks[1]['md5'], 'rate': 1.15, 'followPitch': True, 'version': 'Two [1.15x]'},
            {'uid': 'c', 'md5': picks[1]['md5'], 'rate': 1.3, 'followPitch': False, 'version': 'Two [1.30x]'},
            {'uid': 'd', 'md5': picks[0]['md5'], 'rate': 0.9, 'followPitch': False, 'version': 'One [0.90x]'},
        ],
        'bitrate': 192, 'imageFormat': 'jpg', 'osz': True, 'dest': 'packs',
        'delete': {'enabled': True, 'name': 'delete', 'minutes': 10,
                   'preview': {'mode': 'entry', 'uid': 'b', 'length': 20}},
    }
    try:
        core.export_begin(dict(project, pack={'title': ''}))
        check('empty title refused', False)
    except ExportError:
        check('empty title refused', True)
    plan = core.export_begin(project)
    check('export folder created', os.path.isdir(plan['folder']), plan)
    for image in plan['images'][:2]:
        check('image accepted ' + image['name'], core.export_image(plan['job'], image['name'], b'\xff\xd8fake'))
    check('bad image name refused', not core.export_image(plan['job'], '../x.jpg', b'x'))
    core.export_image(plan['job'], plan['deleteImage'], b'\xff\xd8fake')
    began = time.time()
    check('export started', core.export_run(plan['job']))
    while core.export_status()['state'] == 'running' and time.time() - began < 300:
        time.sleep(0.3)
    status = core.export_status()
    check('export finished', status['state'] == 'done', status.get('error'))
    print('     took %.1fs, %.1f MB' % (time.time() - began, status['size'] / 1e6))
    if status['state'] != 'done':
        return
    files = sorted(os.listdir(plan['folder']))
    print('     ' + '\n     '.join(files))
    check('4 charts + delete', len([f for f in files if f.endswith('.osu')]) == 5)
    check('audio files', {'audio01.mp3', 'audio02.mp3', 'audio03.mp3', 'audio04.mp3', 'delete.mp3'} <= set(files))
    check('osz written', os.path.isfile(status['osz']))
    for item in status['items']:
        print('     %-14s %s' % (item['version'], json.dumps(item['report'])))
    stretch = [i['report'] for i in status['items'] if i['report']['mode'] == 'stretch']
    check('stretched audio verified within 1.5 ms', len(stretch) == 2 and all(
        r['residual_ms'] is not None and abs(r['residual_ms']) < 1.5 for r in stretch), stretch)
    runner = audio.Runner(core.ffmpeg)
    for item, src in zip(status['items'], [picks[0], picks[1], picks[1], picks[0]]):
        got = runner.probe(os.path.join(plan['folder'], 'audio%02d.mp3' % (status['items'].index(item) + 1)))
        want = runner.probe(osufile.audio_path(src['path']))['duration'] / item['rate']
        check('duration %s' % item['version'], got['codec'].startswith('mp3') and abs(got['duration'] - want) < 0.12,
              (got, want))
    d = runner.probe(os.path.join(plan['folder'], 'delete.mp3'))
    check('delete audio is 10:05', abs(d['duration'] - 605) < 0.2, d)
    text = osufile.read(os.path.join(plan['folder'], [f for f in files if '[delete]' in f][0]))
    check('delete preview in the middle', 'PreviewTime: 292000' in text or 'PreviewTime: 293000' in text,
          [l for l in text.splitlines() if l.startswith('PreviewTime')])
    chart = osufile.read(os.path.join(plan['folder'], [f for f in files if '[Two [1.30x]]' in f][0]))
    info = osufile.info_from_text(chart)
    src_info = osufile.info(picks[1]['path'])
    check('chart: metadata', (info['title'], info['creator'], info['version'], info['tags'], info['set_id'])
          == ('Test Pack', 'Tester', 'Two [1.30x]', 'test pack', -1), info)
    check('chart: audio + od', info['audio'] == 'audio03.mp3' and info['od'] == 8.0)
    check('chart: last note scaled', abs(info['last_ms'] - src_info['last_ms'] / 1.3) <= 1,
          (info['last_ms'], src_info['last_ms']))
    check('chart: note count kept', info['notes'] == src_info['notes'])
    check('chart: bpm scaled', abs(info['bpm'] - src_info['bpm'] * 1.3) < 0.01, (info['bpm'], src_info['bpm']))
    check('chart: background only where an image arrived', info['background'] == '' and 'bg01.jpg' in osufile.read(
        os.path.join(plan['folder'], [f for f in files if '[One [1.00x]]' in f][0])))
    core.shutdown()


if __name__ == '__main__':
    test_transform()
    test_lag_estimator()
    test_real_export()
    print('\n%s' % ('ALL OK' if not FAILED else 'FAILED: ' + ', '.join(FAILED)))
    sys.exit(1 if FAILED else 0)
