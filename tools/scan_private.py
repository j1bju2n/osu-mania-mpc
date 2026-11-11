"""Checks a file that is about to be shared for this PC's account name and folder paths.

    python tools/scan_private.py <file> [more files]
Exit code 1 when something is found. For the packaged exe use it on the files that go INTO the exe
(src/mpc/bin/*.exe): the exe itself is compressed.
"""
import os
import re
import sys

user = os.environ.get('USERNAME', '')
found = False
for path in sys.argv[1:]:
    with open(path, 'rb') as f:
        data = f.read()
    hits = []
    for needle in {user.encode(), user.encode('utf-16-le')} - {b''}:
        hits += [m.start() for m in re.finditer(re.escape(needle), data)]
    contexts = set()
    for h in hits:
        start = data.rfind(b':\\', max(0, h - 80), h)
        chunk = data[(start - 1 if start > 0 else h - 24):h + 44]
        contexts.add(''.join(chr(c) if 32 <= c < 127 else '.' for c in chunk))
    print('%s: %d occurrence(s) of the account name' % (os.path.basename(path), len(hits)))
    for c in sorted(contexts)[:8]:
        print('    ' + c)
    found = found or bool(hits)
sys.exit(1 if found else 0)
