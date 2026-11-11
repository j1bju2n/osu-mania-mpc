"""Estimated difficulty (MSD and dan) through the bundled calculator, bin/mmr-calc.exe.

The calculator is Mania Tracker's published `dan-calc` (github.com/aleju03/mania-hub, MIT), built
unchanged for the MMR project next door. It reads a chart file and prints numbers.
The estimate is a guide for keeping a pack's difficulties together, not a verdict.
"""
import json
import logging
import os
import subprocess
import threading

from . import paths

log = logging.getLogger('mpc.calc')
SKILLS = ('Stream', 'Jumpstream', 'Handstream', 'Stamina', 'JackSpeed', 'Chordjack', 'Technical')
GREEK = ('alpha', 'beta', 'gamma', 'delta', 'epsilon', 'zeta', 'eta', 'theta', 'iota', 'kappa')
SEVENK = ('gamma', 'azimuth', 'zenith', 'stellium')
SIXK = ('terra', 'celestial', 'mystery', 'nihility', 'finish')
TIER_FILES = {'--': 'low', '-': 'mid-low', '+': 'mid-high', '++': 'high'}
TIMEOUT = 25.0
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


def dan_text(name, family):
    """The label the way the site writes it: "8+ dan", "delta-", "LN 12 dan"."""
    if not name:
        return ''
    text = name + ' dan' if name[:1].isdigit() else name
    return 'LN ' + text if family == 'ln' else text


def image_for(name, family, keys):
    """Badge artwork for a label, relative to web/dans, or None when there is no art for it."""
    if not name:
        return None
    bare = name.rstrip('+-').strip().lower()
    suffix = name.strip()[len(name.rstrip('+-').strip()):]
    if keys == 7:
        if bare not in tuple(str(i) for i in range(11)) + SEVENK:
            return None
        path = '7k/%s%s.svg' % ('ln-' if family == 'ln' else '', bare)
    elif keys == 6:
        if bare not in tuple(str(i) for i in range(10)) + SIXK:
            return None
        path = '6k/%s%s.svg' % ('ln-' if family == 'ln' else '', bare)
    elif keys not in (4, None):
        return None
    elif family == 'ln' and bare.isdigit() and 1 <= int(bare) <= 17:
        path = 'ln/%s.svg' % bare
    elif bare.isdigit() and 1 <= int(bare) <= 10:
        path = 'reform/%s.svg' % bare
    elif bare in GREEK:
        path = 'reform/%s.webp' % bare
    else:
        return None
    tier = TIER_FILES.get(suffix)
    if tier:
        stem, ext = path.rsplit('.', 1)
        path = '%s-%s.%s' % (stem, tier, ext)
    return path if (paths.web_dir() / 'dans' / path).is_file() else None


class DanCalc:
    def __init__(self, exe=None):
        self.exe = exe or paths.find_calc()
        self._lock = threading.Lock()
        self._proc = None
        self._cache = {}
        self._broken = False

    @property
    def available(self):
        return bool(self.exe) and not self._broken and os.path.isfile(self.exe)

    def _ask(self, path, rate):
        for _attempt in range(2):
            if self._proc is None or self._proc.poll() is not None:
                self._proc = subprocess.Popen([self.exe], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                              stderr=subprocess.DEVNULL, text=True, encoding='utf-8',
                                              creationflags=NO_WINDOW)
            proc = self._proc
            watchdog = threading.Timer(TIMEOUT, proc.kill)       # a stuck chart must not hang the app
            watchdog.start()
            try:
                proc.stdin.write('%s\t%r\n' % (path, float(rate)))
                proc.stdin.flush()
                line = proc.stdout.readline()
            except (OSError, ValueError):
                line = ''
            finally:
                watchdog.cancel()
            if line.strip():
                try:
                    return json.loads(line)
                except ValueError:
                    return {'error': 'unreadable answer'}
            self._proc = None
        return {'error': 'calculator stopped'}

    def summary(self, md5, path, rate=1.0):
        """What the interface shows for one chart at one rate, or None."""
        if not self.available:
            return None
        rate = round(float(rate), 2)
        key = (md5, rate)
        with self._lock:
            if key in self._cache:
                return self._cache[key]
            try:
                answer = self._ask(path, rate)
            except OSError as exc:
                log.warning('calculator failed to start: %s', exc)
                self._broken = True
                return None
            result = None if 'error' in answer else self._shape(answer, rate)
            if len(self._cache) > 4000:
                self._cache.clear()
            self._cache[key] = result
            return result

    @staticmethod
    def _shape(answer, rate):
        msd = answer.get('msd') or {}
        primary = answer.get('primary')
        other = None
        for name in ('rice', 'ln'):
            half = answer.get(name)
            if half and primary and half.get('name') and half.get('family') != primary.get('family'):
                other = half
        overall = msd.get('Overall')
        if not overall and not primary:
            return None
        keys = answer.get('keys')

        def shape(half):
            if not half or not half.get('name'):
                return None
            return {'name': half['name'], 'family': half.get('family') or 'rice', 'raw': half.get('raw'),
                    'text': dan_text(half['name'], half.get('family')),
                    'image': image_for(half['name'], half.get('family'), keys)}
        return {
            'rate': rate, 'keys': keys, 'msd': overall or None,
            'skills': [[name, msd[name]] for name in SKILLS if msd.get(name)],
            'dan': shape(primary), 'danOther': shape(other),
            'rice': shape(answer.get('rice')), 'ln': shape(answer.get('ln')),
            'lnRatio': answer.get('lnRatio'), 'supported': bool(answer.get('supported')),
        }

    def close(self):
        with self._lock:
            if self._proc is not None and self._proc.poll() is None:
                try:
                    self._proc.stdin.close()
                    self._proc.wait(timeout=3)
                except (OSError, subprocess.SubprocessError):
                    self._proc.kill()
            self._proc = None
