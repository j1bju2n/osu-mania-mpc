"""Entry point:  python -m mpc   (and the packaged exe)"""
import sys


def _fatal(text):
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, text, 'Osu!Mania MPC', 0x10)
    except Exception:
        sys.stderr.write(text + '\n')


def run():
    try:
        from mpc.server import main
        return main()
    except Exception as exc:
        import logging
        import traceback
        logging.getLogger('mpc').critical('fatal: %s', traceback.format_exc())
        _fatal('Osu!Mania MPC를 시작하지 못했습니다.\n\n%s: %s\n\n자세한 내용은 로그 폴더를 확인하세요.\n'
               '%%LOCALAPPDATA%%\\MapPackCreate\\logs' % (type(exc).__name__, exc))
        return 1


if __name__ == '__main__':
    sys.exit(run())
