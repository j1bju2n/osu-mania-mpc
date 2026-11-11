"""Reading .osu files and writing the pack's copies of them (rate change + unified metadata).

The source files are only read. Everything here works on text and returns new text.
"""
import math
import os
import re

SECTION = re.compile(r'^\[([A-Za-z]+)\]\s*$')
IMAGE_EXT = ('.jpg', '.jpeg', '.png', '.bmp', '.gif', '.webp')
INVALID_NAME = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def decode(raw):
    if raw.startswith(b'\xef\xbb\xbf'):
        raw = raw[3:]
    return raw.decode('utf-8', 'replace')


def read(path):
    with open(path, 'rb') as f:
        return decode(f.read())


def rnd(value):
    """Round half up, the same way for notes, timing points and breaks so their order never flips."""
    return int(math.floor(value + 0.5))


def split_sections(text):
    """-> (header lines, [(name, [lines])]) keeping every line as it was."""
    head, sections, current = [], [], None
    for line in text.splitlines():
        m = SECTION.match(line.strip())
        if m:
            current = (m.group(1), [])
            sections.append(current)
        elif current is None:
            head.append(line)
        else:
            current[1].append(line)
    return head, sections


def _keyvals(lines):
    out = {}
    for line in lines:
        key, sep, value = line.partition(':')
        if sep and key.strip() and key.strip() not in out:
            out[key.strip()] = value.strip()
    return out


def _num(text, default=0.0):
    try:
        return float(text)
    except (TypeError, ValueError):
        return default


def _background_name(event_lines):
    for line in event_lines:
        s = line.strip()
        if s.startswith('0,0,'):
            rest = s[4:].strip()
            if rest.startswith('"') and rest.find('"', 1) != -1:
                rest = rest[1:rest.find('"', 1)]
            else:
                rest = rest.split(',')[0]
            return rest.strip()
    return ''


def _timing(lines):
    """[(time, beat_length, uninherited)]"""
    out = []
    for line in lines:
        parts = line.strip().split(',')
        if len(parts) < 2:
            continue
        try:
            time, beat = float(parts[0]), float(parts[1])
        except ValueError:
            continue
        red = len(parts) <= 6 or parts[6].strip() != '0'
        out.append((time, beat, red))
    return out


def _objects(lines):
    """[(start, end, is_hold)] in ms."""
    out = []
    for line in lines:
        parts = line.strip().split(',')
        if len(parts) < 5:
            continue
        try:
            start, kind = float(parts[2]), int(parts[3])
        except ValueError:
            continue
        end = start
        if kind & 128 and len(parts) > 5:
            end = _num(parts[5].split(':')[0], start)
        elif kind & 8 and len(parts) > 5:
            end = _num(parts[5], start)
        out.append((start, end, bool(kind & 128)))
    return out


def dominant_bpm(timing, first, last):
    """(bpm that covers the most play time, lowest, highest) from the uninherited points."""
    reds = [(t, b) for t, b, red in timing if red and b > 0]
    if not reds:
        return 0.0, 0.0, 0.0
    reds.sort(key=lambda p: p[0])
    spans = {}
    for i, (t, beat) in enumerate(reds):
        start = first if i == 0 else max(t, first)
        end = reds[i + 1][0] if i + 1 < len(reds) else last
        end = min(end, last)
        bpm = round(60000.0 / beat, 3)
        spans[bpm] = spans.get(bpm, 0.0) + max(0.0, end - start)
    if not any(spans.values()):
        spans = {round(60000.0 / reds[0][1], 3): 1.0}
    used = [b for b, d in spans.items() if d > 0] or list(spans)
    return max(spans, key=spans.get), min(used), max(used)


def info_from_text(text):
    head, sections = split_sections(text)
    by = {}
    for name, lines in sections:
        by.setdefault(name, lines)
    general = _keyvals(by.get('General', []))
    meta = _keyvals(by.get('Metadata', []))
    diff = _keyvals(by.get('Difficulty', []))
    mode = int(_num(general.get('Mode'), 0))
    objects = _objects(by.get('HitObjects', []))
    timing = _timing(by.get('TimingPoints', []))
    first = min((o[0] for o in objects), default=0.0)
    last = max((o[1] for o in objects), default=0.0)
    bpm, bpm_min, bpm_max = dominant_bpm(timing, first, last)
    fmt = 14
    for line in head:
        m = re.search(r'osu file format v(\d+)', line)
        if m:
            fmt = int(m.group(1))
    return {
        'format': fmt, 'mode': mode,
        'keys': int(round(_num(diff.get('CircleSize'), 0))) if mode == 3 else 0,
        'title': meta.get('Title', ''), 'title_u': meta.get('TitleUnicode', ''),
        'artist': meta.get('Artist', ''), 'artist_u': meta.get('ArtistUnicode', ''),
        'creator': meta.get('Creator', ''), 'version': meta.get('Version', ''),
        'source': meta.get('Source', ''), 'tags': meta.get('Tags', ''),
        'set_id': int(_num(meta.get('BeatmapSetID'), -1)),
        'audio': general.get('AudioFilename', ''), 'preview': int(_num(general.get('PreviewTime'), -1)),
        'od': _num(diff.get('OverallDifficulty'), 0), 'hp': _num(diff.get('HPDrainRate'), 0),
        'background': _background_name(by.get('Events', [])),
        'notes': len(objects), 'lns': sum(1 for o in objects if o[2]),
        'first_ms': int(first), 'last_ms': int(last),
        'bpm': bpm, 'bpm_min': bpm_min, 'bpm_max': bpm_max,
    }


def info(path):
    return info_from_text(read(path))


def inside(folder, name):
    """Absolute path of a file named by a beatmap, only if it really is inside the beatmap's folder."""
    if not name:
        return None
    folder = os.path.realpath(folder)
    target = os.path.realpath(os.path.join(folder, name.replace('\\', '/')))
    try:
        if os.path.commonpath([folder, target]) != folder:
            return None
    except ValueError:
        return None
    return target if os.path.isfile(target) else None


def background_path(osu_path, name=None):
    if name is None:
        name = info(osu_path)['background']
    if not name or os.path.splitext(name)[1].lower() not in IMAGE_EXT:
        return None
    return inside(os.path.dirname(osu_path), name)


def audio_path(osu_path, name=None):
    if name is None:
        name = info(osu_path)['audio']
    return inside(os.path.dirname(osu_path), name)


# ---------------------------------------------------------------- writing

def _fmt(value):
    text = ('%.12f' % value).rstrip('0').rstrip('.')
    return text or '0'


def _scale_timing(line, rate):
    parts = line.split(',')
    if len(parts) < 2:
        return line
    try:
        time, beat = float(parts[0]), float(parts[1])
    except ValueError:
        return line
    parts[0] = str(rnd(time / rate))
    red = len(parts) <= 6 or parts[6].strip() != '0'
    if red and beat > 0:
        parts[1] = _fmt(beat / rate)
    return ','.join(parts)


def _scale_object(line, rate):
    parts = line.split(',')
    if len(parts) < 5:
        return line
    try:
        time, kind = float(parts[2]), int(parts[3])
    except ValueError:
        return line
    parts[2] = str(rnd(time / rate))
    if len(parts) > 5:
        if kind & 128:
            end, sep, rest = parts[5].partition(':')
            try:
                parts[5] = str(rnd(float(end) / rate)) + sep + rest
            except ValueError:
                pass
        elif kind & 8:
            try:
                parts[5] = str(rnd(float(parts[5]) / rate))
            except ValueError:
                pass
    return ','.join(parts)


def _set_keys(lines, values, spaced):
    """Replace `Key:value` lines; append the ones that were missing. values keeps insertion order."""
    left = dict(values)
    out = []
    for line in lines:
        key = line.partition(':')[0].strip()
        if ':' in line and key in left:
            out.append(key + (': ' if spaced else ':') + left.pop(key))
        else:
            out.append(line)
    while out and not out[-1].strip():
        out.pop()
    for key in values:
        if key in left:
            out.append(key + (': ' if spaced else ':') + left[key])
    out.append('')
    return out


def transform(text, rate=1.0, audio_name=None, background_name=None, meta=None, od=None, hp=None,
              reset_ids=True):
    """The pack's copy of one difficulty.

    rate: every time is divided by it (the audio is processed to match).
    meta: {'Title','TitleUnicode','Artist','ArtistUnicode','Creator','Version','Source','Tags'} overrides.
    Storyboard and video events are dropped: their files are not part of the pack.
    """
    head, sections = split_sections(text)
    rate = float(rate) or 1.0
    out = [line for line in head if line.strip()] or ['osu file format v14']
    out.append('')
    for name, lines in sections:
        if name == 'General':
            values = {}
            if audio_name:
                values['AudioFilename'] = audio_name
            existing = _keyvals(lines)
            preview = int(_num(existing.get('PreviewTime'), -1))
            if preview >= 0 and rate != 1.0:
                values['PreviewTime'] = str(rnd(preview / rate))
            lines = [l for l in lines if l.partition(':')[0].strip() != 'AudioHash']
            lines = _set_keys(lines, values, True)
        elif name == 'Editor':
            new = []
            for line in lines:
                if line.startswith('Bookmarks') and rate != 1.0:
                    marks = []
                    for part in line.partition(':')[2].split(','):
                        try:
                            marks.append(str(rnd(float(part) / rate)))
                        except ValueError:
                            continue
                    line = 'Bookmarks: ' + ','.join(marks)
                new.append(line)
            lines = new
        elif name == 'Metadata':
            values = dict(meta or {})
            if reset_ids:
                values['BeatmapID'] = '0'
                values['BeatmapSetID'] = '-1'
            lines = _set_keys(lines, values, False)
        elif name == 'Difficulty':
            values = {}
            if od is not None:
                values['OverallDifficulty'] = _fmt(float(od))
            if hp is not None:
                values['HPDrainRate'] = _fmt(float(hp))
            lines = _set_keys(lines, values, False)
        elif name == 'Events':
            breaks = []
            for line in lines:
                s = line.strip()
                if s.startswith('2,') or s.startswith('Break,'):
                    parts = s.split(',')
                    try:
                        breaks.append('2,%d,%d' % (rnd(float(parts[1]) / rate), rnd(float(parts[2]) / rate)))
                    except (ValueError, IndexError):
                        continue
            if background_name is None:
                background_name = _background_name(lines)
            lines = ['//Background and Video events']
            if background_name:
                lines.append('0,0,"%s",0,0' % background_name)
            lines.append('//Break Periods')
            lines.extend(breaks)
            lines += ['//Storyboard Layer 0 (Background)', '//Storyboard Layer 1 (Fail)',
                      '//Storyboard Layer 2 (Pass)', '//Storyboard Layer 3 (Foreground)',
                      '//Storyboard Layer 4 (Overlay)', '//Storyboard Sound Samples', '']
        elif name == 'TimingPoints' and rate != 1.0:
            lines = [_scale_timing(l, rate) if l.strip() else l for l in lines]
        elif name == 'HitObjects' and rate != 1.0:
            lines = [_scale_object(l, rate) if l.strip() else l for l in lines]
        out.append('[%s]' % name)
        out.extend(lines)
        if lines and lines[-1].strip():
            out.append('')
    return '\r\n'.join(out).rstrip('\r\n') + '\r\n'


def delete_difficulty(meta, audio_name, background_name, keys, length_ms, preview_ms):
    """The placeholder difficulty that makes the set count as a marathon (first and last note far apart)."""
    keys = keys if 1 <= keys <= 10 else 4
    width = 512.0 / keys
    first_x = int(width / 2)
    last_x = int(width * (keys - 0.5))
    lines = [
        'osu file format v14', '',
        '[General]', 'AudioFilename: ' + audio_name, 'AudioLeadIn: 0', 'PreviewTime: %d' % preview_ms,
        'Countdown: 0', 'SampleSet: Soft', 'StackLeniency: 0.7', 'Mode: 3', 'LetterboxInBreaks: 0',
        'SpecialStyle: 0', 'WidescreenStoryboard: 0', '',
        '[Editor]', 'DistanceSpacing: 1', 'BeatDivisor: 4', 'GridSize: 16', 'TimelineZoom: 1', '',
        '[Metadata]',
        'Title:' + meta.get('Title', ''), 'TitleUnicode:' + meta.get('TitleUnicode', ''),
        'Artist:' + meta.get('Artist', ''), 'ArtistUnicode:' + meta.get('ArtistUnicode', ''),
        'Creator:' + meta.get('Creator', ''), 'Version:' + meta.get('Version', 'delete'),
        'Source:' + meta.get('Source', ''), 'Tags:' + meta.get('Tags', ''),
        'BeatmapID:0', 'BeatmapSetID:-1', '',
        '[Difficulty]', 'HPDrainRate:8', 'CircleSize:%d' % keys, 'OverallDifficulty:8', 'ApproachRate:5',
        'SliderMultiplier:1.4', 'SliderTickRate:1', '',
        '[Events]', '//Background and Video events',
    ]
    if background_name:
        lines.append('0,0,"%s",0,0' % background_name)
    lines += [
        '//Break Periods', '//Storyboard Layer 0 (Background)', '//Storyboard Layer 1 (Fail)',
        '//Storyboard Layer 2 (Pass)', '//Storyboard Layer 3 (Foreground)', '//Storyboard Layer 4 (Overlay)',
        '//Storyboard Sound Samples', '',
        '[TimingPoints]', '0,500,4,2,0,0,1,0', '', '',
        '[HitObjects]',
        '%d,192,1000,1,0,0:0:0:0:' % first_x,
        '%d,192,%d,1,0,0:0:0:0:' % (last_x, length_ms),
    ]
    return '\r\n'.join(lines) + '\r\n'


def safe_name(text, limit=120, whole=True):
    """Text usable in a file name. whole: it is the complete name, which Windows will not let end in a dot."""
    text = INVALID_NAME.sub('', text or '').strip()[:limit].rstrip()
    if whole:
        text = text.rstrip('. ')
    return text or 'untitled'


def format_rate(rate):
    return '%.2f' % float(rate)
