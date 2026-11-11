"""Audio for the pack: everything becomes 44.1 kHz MP3, with the chart's offset kept exactly.

What was measured while building this (ffmpeg 9.0 + BASS 2.4.17, the decoder family osu!stable uses):
  * An MP3 written by ffmpeg/LAME with its info tag decodes with no shift at all in BASS and in ffmpeg,
    so OGG/FLAC -> MP3 does not move the offset (error 0.02 ms).
  * A source MP3 WITHOUT a LAME gapless tag is decoded differently: BASS drops the 529 sample decoder
    delay, ffmpeg drops nothing. Converting such a file naively makes it 12 ms late in game.
    -> those sources get 529 samples trimmed before anything else.
  * Resampling (asetrate) is sample exact. Pitch-preserving stretches are not: ffmpeg's atempo lands
    7-15 ms off, rubberband 2-9 ms off depending on the rate.
    -> the stretched audio is compared with the exact resampled timeline (onset envelopes, several
       windows along the song) and shifted by the measured amount before encoding; the leftover is
       measured again on the finished MP3 and reported.
"""
import logging
import math
import os
import re
import subprocess
import threading
from array import array
from operator import mul

log = logging.getLogger('mpc.audio')
SR = 44100
ENV_SR = 8000
BIN = 8                         # 1 ms envelope bins
DECODER_DELAY = 529
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


class AudioError(Exception):
    pass


class Cancelled(Exception):
    pass


class Runner:
    """Runs ffmpeg; one cancel() stops whatever is running."""

    def __init__(self, ffmpeg):
        self.ffmpeg = ffmpeg
        self._lock = threading.Lock()
        self._procs = set()
        self.cancelled = False

    def cancel(self):
        self.cancelled = True
        with self._lock:
            for proc in self._procs:
                if proc.poll() is None:
                    proc.kill()

    def run(self, args, capture=False):
        if self.cancelled:
            raise Cancelled()
        if not self.ffmpeg:
            raise AudioError('ffmpeg.exe를 찾지 못했습니다.')
        cmd = [self.ffmpeg, '-hide_banner', '-nostdin', '-loglevel', 'error', '-y'] + list(args)
        with self._lock:
            proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL,
                                    stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
                                    stderr=subprocess.PIPE, creationflags=NO_WINDOW)
            self._procs.add(proc)
        try:
            out, err = proc.communicate()
        finally:
            with self._lock:
                self._procs.discard(proc)
        if self.cancelled:
            raise Cancelled()
        if proc.returncode:
            raise AudioError(err.decode('utf-8', 'replace').strip()[-600:] or 'ffmpeg 오류')
        return out

    def probe(self, path):
        """{'codec','sample_rate','duration','start'} read from ffmpeg's own description of the file."""
        proc = subprocess.run([self.ffmpeg, '-hide_banner', '-nostdin', '-i', path], stdin=subprocess.DEVNULL,
                              capture_output=True, creationflags=NO_WINDOW)
        text = proc.stderr.decode('utf-8', 'replace')
        info = {'codec': '', 'sample_rate': 0, 'duration': 0.0, 'start': 0.0}
        m = re.search(r'Duration: (\d+):(\d+):(\d+(?:\.\d+)?)', text)
        if m:
            info['duration'] = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
        m = re.search(r'start: (-?\d+(?:\.\d+)?)', text)
        if m:
            info['start'] = float(m.group(1))
        m = re.search(r'Stream #\d+:\d+[^\n]*?: Audio: (\w+)[^\n]*?(\d+) Hz', text)
        if m:
            info['codec'] = m.group(1).lower()
            info['sample_rate'] = int(m.group(2))
        if not info['codec']:
            raise AudioError('오디오를 읽지 못했습니다: %s' % os.path.basename(path))
        return info


def needs_delay_trim(info):
    """MP3 with no gapless tag: ffmpeg keeps the decoder delay that BASS (osu!) drops."""
    return info['codec'].startswith('mp3') and info['start'] < 0.0005


def pre_chain(info):
    chain = []
    if needs_delay_trim(info):
        chain += ['atrim=start_sample=%d' % DECODER_DELAY, 'asetpts=PTS-STARTPTS']
    chain.append('aresample=%d' % SR)
    return chain


def exact_chain(info, rate):
    """Sample-exact speed change; pitch moves with the rate."""
    chain = pre_chain(info)
    if abs(rate - 1.0) > 1e-9:
        chain += ['asetrate=%d*%.6f' % (SR, rate), 'aresample=%d' % SR]
    return chain


def stretch_chain(info, rate):
    """Pitch-preserving speed change (short window: transients stay closest to where they belong)."""
    return pre_chain(info) + ['rubberband=tempo=%.6f:window=short' % rate]


def mp3_args(bitrate):
    return ['-map_metadata', '-1', '-vn', '-c:a', 'libmp3lame', '-b:a', '%dk' % int(bitrate),
            '-ar', str(SR), '-ac', '2', '-write_xing', '1', '-id3v2_version', '3']


# ---------------------------------------------------------------- measuring a shift

def _envelope(pcm_bytes):
    """Onset strength per millisecond from 8 kHz mono PCM."""
    pcm = array('h')
    pcm.frombytes(pcm_bytes[:len(pcm_bytes) // 2 * 2])
    view = memoryview(pcm)
    n = len(pcm) // BIN
    env = [float(sum(map(abs, view[i * BIN:(i + 1) * BIN]))) for i in range(n)]
    if n < 8:
        return []
    smooth = [0.0] * n
    for i in range(2, n - 2):
        smooth[i] = (env[i - 2] + 2 * env[i - 1] + 3 * env[i] + 2 * env[i + 1] + env[i + 2]) / 9.0
    floor = 30.0 * BIN
    logs = [math.log(v + floor) for v in smooth]
    return [max(0.0, logs[i + 1] - logs[i]) for i in range(n - 1)]


def _window_lag(ref, test, start, length, span):
    a = ref[start:start + length]
    if len(a) < length or start - span < 0 or start + length + span > len(test):
        return None
    mean = sum(a) / length
    if mean <= 1e-6:
        return None                                   # silence: nothing to line up
    a = [v - mean for v in a]
    scores = [sum(map(mul, a, test[start + k:start + k + length])) for k in range(-span, span + 1)]
    best = max(range(len(scores)), key=scores.__getitem__)
    peak = scores[best]
    if peak <= 0:
        return None
    frac = 0.0
    if 0 < best < len(scores) - 1:
        y0, y1, y2 = scores[best - 1], scores[best], scores[best + 1]
        denom = y0 - 2 * y1 + y2
        if denom:
            frac = 0.5 * (y0 - y2) / denom
    elif best in (0, len(scores) - 1):
        return None                                   # ran into the edge of the search range
    return (best + frac - span) * BIN * 1000.0 / ENV_SR


def measure_lag(ref, test, windows=7, seconds=10, span_ms=45):
    """How late `test` is against `ref`, in ms: (median, spread, number of windows used)."""
    per_ms = ENV_SR // BIN // 1000 or 1
    span = span_ms * per_ms
    total = min(len(ref), len(test))
    length = min(seconds * 1000 * per_ms, max(0, total - 2 * span - 1))
    if length < 1500 * per_ms:
        return 0.0, 0.0, 0
    room = total - length - 2 * span
    lags = []
    for i in range(windows):
        start = span + (room * i // (windows - 1) if windows > 1 else room // 2)
        lag = _window_lag(ref, test, start, length, span)
        if lag is not None:
            lags.append(lag)
    if not lags:
        return 0.0, 0.0, 0
    lags.sort()
    # the middle half: one window caught on a neighbouring beat must not move the result
    core = lags[len(lags) // 4:len(lags) - len(lags) // 4] or lags
    median = core[len(core) // 2] if len(core) % 2 else (core[len(core) // 2 - 1] + core[len(core) // 2]) / 2
    return median, core[-1] - core[0], len(lags)


def envelope_of(runner, source, chain=None):
    args = ['-i', source, '-vn']
    if chain:
        args += ['-af', ','.join(chain)]
    args += ['-ar', str(ENV_SR), '-ac', '1', '-f', 's16le', '-c:a', 'pcm_s16le', '-']
    return _envelope(runner.run(args, capture=True))


# ---------------------------------------------------------------- rendering

def render(runner, source, target, rate, follow_pitch, bitrate, work_dir, verify=True):
    """source audio -> target .mp3 at `rate`.

    Returns {'mode', 'trimmed', 'shift_ms', 'spread_ms', 'residual_ms'}; shift_ms is what the
    pitch-preserving stretch was off by and was corrected for, residual_ms what is left afterwards.
    """
    info = runner.probe(source)
    report = {'mode': 'copy', 'trimmed': needs_delay_trim(info), 'shift_ms': None, 'spread_ms': None,
              'residual_ms': None}
    unity = abs(rate - 1.0) < 1e-9
    if unity and info['codec'].startswith('mp3') and source.lower().endswith('.mp3'):
        report['trimmed'] = False                    # the very same bytes: nothing can move
        with open(source, 'rb') as fin, open(target, 'wb') as fout:
            while True:
                block = fin.read(1 << 20)
                if not block:
                    break
                fout.write(block)
        return report
    if unity or follow_pitch:
        report['mode'] = 'convert' if unity else 'resample'
        runner.run(['-i', source, '-af', ','.join(exact_chain(info, rate))] + mp3_args(bitrate) + [target])
        return report

    report['mode'] = 'stretch'
    os.makedirs(work_dir, exist_ok=True)
    temp = os.path.join(work_dir, 'stretch_%d_%d.wav' % (os.getpid(), threading.get_ident()))
    try:
        runner.run(['-i', source, '-vn', '-af', ','.join(stretch_chain(info, rate)), '-ar', str(SR), '-ac', '2',
                    '-c:a', 'pcm_s16le', temp])
        ref = envelope_of(runner, source, exact_chain(info, rate))
        lag, spread, used = measure_lag(ref, envelope_of(runner, temp))
        fix = []
        if used:
            samples = int(round(abs(lag) * SR / 1000.0))
            if samples and lag > 0:
                fix = ['atrim=start_sample=%d' % samples, 'asetpts=PTS-STARTPTS']
            elif samples:
                fix = ['adelay=%dS:all=1' % samples]
            report['shift_ms'] = round(lag, 2)
            report['spread_ms'] = round(spread, 2)
        args = ['-i', temp]
        if fix:
            args += ['-af', ','.join(fix)]
        runner.run(args + mp3_args(bitrate) + [target])
        if verify and used:
            residual, _, again = measure_lag(ref, envelope_of(runner, target))
            if again:
                report['residual_ms'] = round(residual, 2)
    finally:
        try:
            os.remove(temp)
        except OSError:
            pass
    return report


def render_delete_audio(runner, target, seconds, clip=None, clip_start=0.0, clip_seconds=30.0):
    """The placeholder difficulty's audio: silence, optionally with a preview clip in the middle.

    Returns the time (ms) the clip starts at, or -1 when there is none.
    """
    seconds = float(seconds)
    if not clip:
        runner.run(['-f', 'lavfi', '-t', '%.3f' % seconds, '-i', 'anullsrc=r=22050:cl=mono',
                    '-map_metadata', '-1', '-c:a', 'libmp3lame', '-b:a', '16k', '-ar', '22050', '-ac', '1', target])
        return -1
    clip_seconds = max(3.0, min(float(clip_seconds), seconds - 20.0))
    before = round((seconds - clip_seconds) / 2.0)
    after = seconds - before - clip_seconds
    fade = min(2.0, clip_seconds / 4.0)
    graph = ('[1:a]aresample=%d,aformat=sample_fmts=fltp:channel_layouts=stereo,'
             'apad=whole_dur=%.3f,atrim=end=%.3f,afade=t=in:d=0.25,afade=t=out:st=%.3f:d=%.3f[c];'
             '[0:a][c][2:a]concat=n=3:v=0:a=1[o]') % (SR, clip_seconds, clip_seconds, clip_seconds - fade, fade)
    silence = 'anullsrc=r=%d:cl=stereo' % SR
    runner.run(['-f', 'lavfi', '-t', '%.3f' % before, '-i', silence,
                '-ss', '%.3f' % max(0.0, clip_start), '-t', '%.3f' % clip_seconds, '-i', clip,
                '-f', 'lavfi', '-t', '%.3f' % after, '-i', silence,
                '-filter_complex', graph, '-map', '[o]', '-map_metadata', '-1',
                '-c:a', 'libmp3lame', '-q:a', '5', '-ar', str(SR), '-ac', '2', target])
    return int(before * 1000)
