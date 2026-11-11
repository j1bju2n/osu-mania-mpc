"""What icon does Windows Explorer currently show for a file, and (with --refresh) make it look again.

    python tools/shell_icon.py <file> <out.png> [--refresh]
Explorer keeps icons in a cache keyed by path, so a rebuilt exe can go on showing the icon of the build
before it. --refresh tells the shell that this one file changed (SHChangeNotify, the same notice a
program sends after saving a file); nothing is deleted and no setting is touched.
Needs Pillow (development only).
"""
import ctypes
import os
import sys
from ctypes import wintypes

from PIL import Image

path = os.path.abspath(sys.argv[1])
out = sys.argv[2]
shell32, user32, gdi32 = ctypes.windll.shell32, ctypes.windll.user32, ctypes.windll.gdi32

if '--refresh' in sys.argv:
    SHCNE_UPDATEITEM, SHCNE_UPDATEDIR, SHCNF_PATHW, SHCNF_FLUSH = 0x2000, 0x1000, 0x0005, 0x1000
    shell32.SHChangeNotify.argtypes = [wintypes.LONG, wintypes.UINT, ctypes.c_wchar_p, ctypes.c_void_p]
    shell32.SHChangeNotify(SHCNE_UPDATEITEM, SHCNF_PATHW | SHCNF_FLUSH, path, None)
    shell32.SHChangeNotify(SHCNE_UPDATEDIR, SHCNF_PATHW | SHCNF_FLUSH, os.path.dirname(path), None)
    if '--all' in sys.argv:          # "icons may have changed": Explorer redraws every icon once
        shell32.SHChangeNotify(0x08000000, 0x1000, None, None)       # SHCNE_ASSOCCHANGED, SHCNF_IDLIST | SHCNF_FLUSH


class SHFILEINFOW(ctypes.Structure):
    _fields_ = [('hIcon', wintypes.HANDLE), ('iIcon', ctypes.c_int), ('dwAttributes', wintypes.DWORD),
                ('szDisplayName', wintypes.WCHAR * 260), ('szTypeName', wintypes.WCHAR * 80)]


class ICONINFO(ctypes.Structure):
    _fields_ = [('fIcon', wintypes.BOOL), ('xHotspot', wintypes.DWORD), ('yHotspot', wintypes.DWORD),
                ('hbmMask', wintypes.HBITMAP), ('hbmColor', wintypes.HBITMAP)]


class BITMAP(ctypes.Structure):
    _fields_ = [('bmType', wintypes.LONG), ('bmWidth', wintypes.LONG), ('bmHeight', wintypes.LONG),
                ('bmWidthBytes', wintypes.LONG), ('bmPlanes', wintypes.WORD), ('bmBitsPixel', wintypes.WORD),
                ('bmBits', ctypes.c_void_p)]


ctypes.windll.ole32.CoInitialize(None)
info = SHFILEINFOW()
shell32.SHGetFileInfoW.argtypes = [ctypes.c_wchar_p, wintypes.DWORD, ctypes.POINTER(SHFILEINFOW), wintypes.UINT, wintypes.UINT]
shell32.SHGetFileInfoW.restype = ctypes.c_void_p
shell32.SHGetFileInfoW(path, 0, ctypes.byref(info), ctypes.sizeof(info), 0x100)          # SHGFI_ICON (large)
if not info.hIcon:
    sys.exit('the shell gave no icon')
icon = ICONINFO()
user32.GetIconInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(ICONINFO)]
user32.GetIconInfo(info.hIcon, ctypes.byref(icon))
bm = BITMAP()
gdi32.GetObjectW.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p]
gdi32.GetObjectW(icon.hbmColor, ctypes.sizeof(bm), ctypes.byref(bm))
size = bm.bmWidth * bm.bmHeight * 4
buf = ctypes.create_string_buffer(size)
gdi32.GetBitmapBits.argtypes = [wintypes.HANDLE, wintypes.LONG, ctypes.c_void_p]
gdi32.GetBitmapBits(icon.hbmColor, size, buf)
Image.frombuffer('RGBA', (bm.bmWidth, bm.bmHeight), buf.raw, 'raw', 'BGRA', 0, 1).resize((128, 128), Image.NEAREST).save(out)
print('shell icon index %d, %dx%d -> %s' % (info.iIcon, bm.bmWidth, bm.bmHeight, out))
