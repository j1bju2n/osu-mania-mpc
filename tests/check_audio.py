"""Checks the audio pipeline on real files, against an independent (numpy) measurement.

usage: python tests/check_audio.py <audio file> [more files]
Needs numpy (development only; the program itself does not).
"""
import os
import subprocess
import sys
import tempfile
import time

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))
from mpc import audio, paths  # noqa: E402

FFMPEG = paths.find_ffmpeg()
SR = 44100
BIN = 22


def pcm(path, chain=None):
    args = [FFMPEG, '-hide_banner', '-loglevel', 'error', '-i', path, '-vn']
    if chain:
        args += ['-af', ','.join(chain)]
    out = subprocess.run(args + ['-ar', str(SR), '-ac', '1', '-f', 's16le', '-c:a', 'pcm_s16le', '-'],
                         capture_output=True)
    return np.frombuffer(out.stdout, '<i2').astype(np.float64)


def onset(data):
    n = len(data) // BIN
    env = np.abs(data[:n * BIN]).reshape(n, BIN).mean(axis=1)
    k = np.hanning(9)
    env = np.convolve(env, k / k.sum(), mode='same')
    return np.maximum(np.diff(np.log(env + 30.0)), 0.0)


def lags(ref, test):
    span, length = int(0.06 * SR / BIN), int(10 * SR / BIN)
    total = min(len(ref), len(test))
    out = []
    for i in range(9):
        start = span + int((total - length - 2 * span) * i / 8)
        a = ref[start:start + length]
        b = test[start - span:start + length + span]
        corr = np.correlate(b - b.mean(), a - a.mean(), mode='valid')
        k = int(np.argmax(corr))
        frac = 0.0
        if 0 < k < len(corr) - 1:
            y0, y1, y2 = corr[k - 1], corr[k], corr[k + 1]
            frac = 0.5 * (y0 - y2) / (y0 - 2 * y1 + y2)
        out.append((k + frac - span) * BIN / SR * 1000.0)
    return np.array(out)


def main():
    runner = audio.Runner(FFMPEG)
    work = tempfile.mkdtemp(prefix='mpc-audio-')
    for source in sys.argv[1:]:
        info = runner.probe(source)
        print('\n# %s  %s' % (os.path.basename(source), info))
        for rate in (0.85, 1.0, 1.1, 1.25, 1.46):
            for follow in (False, True):
                if rate == 1.0 and follow:
                    continue
                target = os.path.join(work, 'out_%s_%s.mp3' % (rate, follow))
                began = time.time()
                report = audio.render(runner, source, target, rate, follow, 192, work)
                took = time.time() - began
                ref = onset(pcm(source, audio.exact_chain(info, rate)))
                got = lags(ref, onset(pcm(target)))
                core = np.sort(got)[2:-2]
                print('%.2fx %-8s %-8s corrected %-6s residual(app) %-6s | independent median %+5.2f ms '
                      '(middle windows %+5.2f..%+5.2f) | %.1fs %.1f MB' % (
                          rate, 'pitch' if follow else 'keep', report['mode'], report['shift_ms'],
                          report['residual_ms'], float(np.median(got)), core.min(), core.max(), took,
                          os.path.getsize(target) / 1e6))


if __name__ == '__main__':
    main()
