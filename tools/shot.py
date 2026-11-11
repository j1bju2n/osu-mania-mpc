"""Screenshot of the dev server's interface with a windowless (headless) Edge: nothing appears on screen.

    python tools/shot.py <view> <out.png> [width height]
view: start (as on a normal start) | pick | pack | thumb | meta | rate.  The dev server (tools/dev_server.py) must be running.
The page opens with #view=<view>, which the interface honours on start.
"""
import os
import subprocess
import sys
import tempfile

view, out = sys.argv[1], os.path.abspath(sys.argv[2])
width, height = (sys.argv[3], sys.argv[4]) if len(sys.argv) > 4 else ('1480', '900')
edge = None
for root in (os.environ.get('ProgramFiles(x86)'), os.environ.get('ProgramFiles')):
    candidate = os.path.join(root or '', 'Microsoft', 'Edge', 'Application', 'msedge.exe')
    if os.path.isfile(candidate):
        edge = candidate
        break
if not edge:
    sys.exit('Edge not found')
profile = os.path.join(tempfile.gettempdir(), 'mpc-dev', 'shot-profile')
url = 'http://127.0.0.1:8791/?t=dev' + ('' if view == 'start' else '#view=' + view)
subprocess.run([edge, '--headless=new', '--disable-gpu', '--hide-scrollbars', '--no-first-run',
                '--user-data-dir=' + profile, '--window-size=%s,%s' % (width, height),
                '--virtual-time-budget=9000', '--screenshot=' + out, url],
               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=90)
print(out if os.path.isfile(out) else 'no screenshot produced')
