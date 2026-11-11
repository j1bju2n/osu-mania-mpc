"""A stand-in process laid out like the parts of osu!stable that mmr.live reads.

Prints its pid when ready. Commands on stdin:  md5 <hex> | file <folder>|<name> | none | state <n> | quit
Addresses are kept below 4 GB because the real client is a 32-bit process.
"""
import ctypes
import os
import sys
from ctypes import wintypes

BASE_PATTERN = bytes.fromhex('F80174048365')
STATE_PATTERN = bytes.fromhex('4883F804731E')

k = ctypes.WinDLL('kernel32')
k.VirtualAlloc.restype = ctypes.c_void_p
k.VirtualAlloc.argtypes = [ctypes.c_void_p, ctypes.c_size_t, wintypes.DWORD, wintypes.DWORD]
region = None
for wanted in (0x30000000, 0x41000000, 0x52000000, 0x23000000, 0x64000000):
    region = k.VirtualAlloc(wanted, 0x10000, 0x3000, 0x40)       # commit+reserve, RWX like JIT code
    if region:
        break
if not region:
    sys.exit('no low memory available')


def put(offset, data):
    ctypes.memmove(region + offset, data, len(data))


def u32(value):
    return int(value).to_bytes(4, 'little')


CODE, SLOT, BEATMAP, STRING, STATE_CODE, STATE_SLOT = 0x100, 0x800, 0x1000, 0x2000, 0x300, 0x900
FOLDER, NAME = 0x3000, 0x4000
put(CODE, BASE_PATTERN)
put(CODE - 0xC, u32(region + SLOT))          # [base - 0xC] -> static slot
put(SLOT, u32(region + BEATMAP))             # slot -> beatmap object
put(BEATMAP + 0x6C, u32(region + STRING))    # beatmap + 0x6C -> .NET string
put(BEATMAP + 0x78, u32(region + FOLDER))
put(BEATMAP + 0x90, u32(region + NAME))
put(STATE_CODE, STATE_PATTERN)
put(STATE_CODE - 0x4, u32(region + STATE_SLOT))
put(STATE_SLOT, u32(5))


def set_md5(text):
    put(STRING, u32(0x12345678) + u32(len(text)) + text.encode('utf-16-le'))


def set_text(offset, text):
    put(offset, u32(0x12345678) + u32(len(text)) + text.encode('utf-16-le'))


set_text(FOLDER, '')
set_text(NAME, '')
set_md5(sys.argv[1] if len(sys.argv) > 1 else 'a' * 32)
print(os.getpid(), flush=True)
for line in sys.stdin:
    parts = line.split()
    if not parts:
        continue
    if parts[0] == 'md5':
        set_md5(parts[1])
        put(SLOT, u32(region + BEATMAP))
    elif parts[0] == 'file':
        folder, _, name = line.split(' ', 1)[1].strip().partition('|')
        set_text(FOLDER, folder)
        set_text(NAME, name)
    elif parts[0] == 'none':
        put(SLOT, u32(0))
    elif parts[0] == 'state':
        put(STATE_SLOT, u32(int(parts[1])))
    elif parts[0] == 'quit':
        break
    print('ok', flush=True)
