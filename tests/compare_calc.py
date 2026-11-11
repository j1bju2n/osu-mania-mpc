"""Two builds of mmr-calc.exe must print the same numbers.

    python tests/compare_calc.py <old exe> <new exe>     (reads a handful of 4K/7K charts from the osu! folder)
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))
from mpc.osudb import Library  # noqa: E402

old, new = sys.argv[1], sys.argv[2]
lib = Library()
lib.load(os.path.join(os.environ['LOCALAPPDATA'], 'osu!'))
charts = []
for keys, want in ((4, 14), (7, 4), (6, 2)):
    step = max(1, len([e for e in lib.entries if e['keys'] == keys]) // want)
    charts += [e['path'] for e in lib.entries if e['keys'] == keys][::step][:want]
charts = [c for c in charts if os.path.isfile(c)]
requests = ''.join('%s\t%s\n' % (c, r) for c in charts for r in (1.0, 1.25, 0.85))


def ask(exe):
    out = subprocess.run([exe], input=requests, capture_output=True, text=True, encoding='utf-8', timeout=600)
    return out.stdout.splitlines()


a, b = ask(old), ask(new)
same = sum(1 for x, y in zip(a, b) if x == y)
print('%d charts x 3 rates = %d answers; identical: %d; old %d lines, new %d lines' % (len(charts), len(a), same, len(a), len(b)))
for x, y in zip(a, b):
    if x != y:
        print('DIFF\n  ' + x[:200] + '\n  ' + y[:200])
        break
sys.exit(0 if a == b and a else 1)
