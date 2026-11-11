"""Entry script for the packaged exe (PyInstaller needs a plain script to start from)."""
import sys

from mpc.__main__ import run

sys.exit(run())
