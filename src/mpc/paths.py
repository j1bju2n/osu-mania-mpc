"""Where things live: per-user data, bundled resources, and the external tools (ffmpeg, calculator)."""
import json
import logging
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path


def _local_appdata():
    return Path(os.environ.get('LOCALAPPDATA') or (Path.home() / 'AppData' / 'Local'))


def data_dir():
    override = os.environ.get('MPC_DATA_DIR')
    return Path(override) if override else _local_appdata() / 'MapPackCreate'


def frozen():
    return bool(getattr(sys, 'frozen', False))


def app_dir():
    """Folder the user sees: where the exe is, or the project root when run from source."""
    if frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent.parent


def resource_dir():
    """Folder holding the packaged files (web, bin): the unpack folder of the exe, or this package."""
    if frozen():
        return Path(getattr(sys, '_MEIPASS', app_dir())) / 'mpc'
    return Path(__file__).resolve().parent


def web_dir():
    return resource_dir() / 'web'


def packs_dir():
    override = os.environ.get('MPC_PACKS_DIR')
    return Path(override) if override else app_dir() / 'packs'


def assets_dir():
    return data_dir() / 'assets'


def work_dir():
    return data_dir() / 'work'


def settings_path():
    return data_dir() / 'settings.json'


def project_path():
    return data_dir() / 'project.json'


def find_calc():
    override = os.environ.get('MPC_CALC')
    if override:
        return override
    for folder in (resource_dir() / 'bin', app_dir() / 'bin', app_dir()):
        target = folder / 'mmr-calc.exe'
        if target.is_file():
            return str(target)
    return ''


def find_ffmpeg():
    """ffmpeg.exe next to the program first, then PATH, then a copy another tool installed."""
    override = os.environ.get('MPC_FFMPEG')
    if override and os.path.isfile(override):
        return override
    for folder in (app_dir(), app_dir() / 'bin', resource_dir() / 'bin'):
        target = folder / 'ffmpeg.exe'
        if target.is_file():
            return str(target)
    on_path = shutil.which('ffmpeg')
    if on_path:
        return on_path
    companella = _local_appdata() / 'Companella'
    try:
        builds = sorted((p for p in companella.glob('app-*') if (p / 'ffmpeg.exe').is_file()),
                        key=lambda p: [int(x) if x.isdigit() else 0 for x in p.name[4:].split('.')])
    except OSError:
        builds = []
    return str(builds[-1] / 'ffmpeg.exe') if builds else ''


def load_json(path, default):
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8'))
        return data if isinstance(data, type(default)) else default
    except (OSError, ValueError):
        return default


def save_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    tmp.replace(path)


def init_logging():
    folder = data_dir() / 'logs'
    folder.mkdir(parents=True, exist_ok=True)
    for old in sorted(folder.glob('mpc_*.log'))[:-14]:
        try:
            old.unlink()
        except OSError:
            pass
    filename = folder / ('mpc_' + datetime.now().strftime('%Y%m%d_%H%M%S') + '.log')
    handler = logging.FileHandler(filename, encoding='utf-8')
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s'))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    return filename
