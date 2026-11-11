"""Development server: the interface on a fixed port with a fixed token, no window, data in a temp folder.

    python tools/dev_server.py        then open  http://127.0.0.1:8791/?t=dev
The osu! folder is only read. Exports go to a temp folder, not next to the program.
To act as osu!: create live.txt in %TEMP%/mpc-dev before starting; write an md5, `none` or `off` into it.
"""
import os
import sys
import tempfile

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, os.path.join(ROOT, 'src'))
base = os.path.join(tempfile.gettempdir(), 'mpc-dev')
os.environ.setdefault('MPC_DATA_DIR', os.path.join(base, 'data'))
os.environ.setdefault('MPC_PACKS_DIR', os.path.join(base, 'packs'))
os.environ.setdefault('MPC_PORT', '8791')
os.environ.setdefault('MPC_TOKEN', 'dev')
os.environ.setdefault('MPC_NO_WINDOW', '1')

from mpc import live  # noqa: E402

LIVE_FILE = os.path.join(base, 'live.txt')


class FileWatcher:
    """Stands in for a running osu!: live.txt holds an md5, `none` (nothing selected) or `off` (osu! closed)."""

    def __init__(self, *args, **kwargs):
        pass

    def start(self):
        pass

    def stop(self):
        pass

    def snapshot(self):
        try:
            with open(LIVE_FILE, encoding='utf-8') as f:
                word = f.read().strip().lower()
        except OSError:
            word = 'off'
        on = word != 'off'
        md5 = word if len(word) == 32 else None
        return {'running': on, 'readable': on, 'md5': md5, 'state': 5 if on else None,
                'label': '곡 선택' if on else '', 'problem': '', 'file': None}


if os.path.exists(LIVE_FILE):                 # without the file the real osu! reader is used
    live.LiveWatcher = FileWatcher

from mpc.server import main  # noqa: E402

sys.exit(main())
