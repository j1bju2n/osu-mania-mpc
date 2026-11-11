"""Makes the program icon (src/mpc/web/mpc.ico, also the window's favicon) from the artwork in docs/icon-source.webp.

    python tools/make_icon.py            (needs Pillow; development only)
The artwork is a dark rounded square on a white sheet. The white around it becomes transparent, the square is
cropped to fill the icon, and the sizes Windows asks for are written into one .ico. docs/icon.png keeps a
512 px copy for other uses.
"""
import os

from PIL import Image, ImageChops, ImageDraw, ImageFilter

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
SOURCE = os.path.join(ROOT, 'docs', 'icon-source.webp')
SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)
MARK = (255, 0, 255)

art = Image.open(SOURCE).convert('RGBA')
flat = Image.new('RGB', art.size, (255, 255, 255))
flat.paste(art, mask=art.split()[3])

# the sheet: everything white that is connected to the corners (the white strokes inside the square are not)
sheet = flat.copy()
for corner in ((0, 0), (sheet.width - 1, 0), (0, sheet.height - 1), (sheet.width - 1, sheet.height - 1)):
    ImageDraw.floodfill(sheet, corner, MARK, thresh=60)
r, g, b = sheet.split()
outside = ImageChops.multiply(ImageChops.multiply(r.point(lambda v: 255 if v == 255 else 0),
                                                  g.point(lambda v: 255 if v == 0 else 0)),
                              b.point(lambda v: 255 if v == 255 else 0))
inside = ImageChops.invert(outside)
box = inside.getbbox()
# pull the edge in by two pixels and soften it: the pale fringe where the square met the sheet goes away
alpha = inside.filter(ImageFilter.MinFilter(5)).filter(ImageFilter.GaussianBlur(1.1))
icon = flat.convert('RGBA')
icon.putalpha(alpha)
icon = icon.crop(box)
side = max(icon.size)
square = Image.new('RGBA', (side, side), (0, 0, 0, 0))
square.paste(icon, ((side - icon.width) // 2, (side - icon.height) // 2))

square.resize((512, 512), Image.LANCZOS).save(os.path.join(ROOT, 'docs', 'icon.png'))
big = square.resize((256, 256), Image.LANCZOS)
big.save(os.path.join(ROOT, 'src', 'mpc', 'web', 'mpc.ico'), sizes=[(s, s) for s in SIZES])
print('artwork %s, square found at %s (%d px), wrote mpc.ico with sizes %s' % (art.size, box, side, list(SIZES)))
