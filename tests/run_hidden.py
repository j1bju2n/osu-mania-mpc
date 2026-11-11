"""Run a command on a separate, never-displayed Windows desktop and wait for it.

Used to exercise the real GUI without showing windows or taking focus on the desktop the
user is working on.   py tests\\run_hidden.py <timeout seconds> <program> [args...]
"""
import ctypes
import subprocess
import sys
from ctypes import wintypes

user32 = ctypes.WinDLL('user32', use_last_error=True)
kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)


class STARTUPINFO(ctypes.Structure):
    _fields_ = [('cb', wintypes.DWORD), ('lpReserved', wintypes.LPWSTR), ('lpDesktop', wintypes.LPWSTR),
                ('lpTitle', wintypes.LPWSTR), ('dwX', wintypes.DWORD), ('dwY', wintypes.DWORD),
                ('dwXSize', wintypes.DWORD), ('dwYSize', wintypes.DWORD), ('dwXCountChars', wintypes.DWORD),
                ('dwYCountChars', wintypes.DWORD), ('dwFillAttribute', wintypes.DWORD),
                ('dwFlags', wintypes.DWORD), ('wShowWindow', wintypes.WORD), ('cbReserved2', wintypes.WORD),
                ('lpReserved2', ctypes.c_void_p), ('hStdInput', wintypes.HANDLE),
                ('hStdOutput', wintypes.HANDLE), ('hStdError', wintypes.HANDLE)]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [('hProcess', wintypes.HANDLE), ('hThread', wintypes.HANDLE),
                ('dwProcessId', wintypes.DWORD), ('dwThreadId', wintypes.DWORD)]


def main():
    timeout = int(sys.argv[1])
    command = subprocess.list2cmdline(sys.argv[2:])
    user32.CreateDesktopW.restype = wintypes.HANDLE
    user32.CreateDesktopW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_void_p, wintypes.DWORD,
                                      wintypes.DWORD, ctypes.c_void_p]
    desk = user32.CreateDesktopW('mpc_ui_test', None, None, 0, 0x10000000, None)
    if not desk:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        si = STARTUPINFO()
        si.cb = ctypes.sizeof(si)
        si.lpDesktop = 'mpc_ui_test'
        pi = PROCESS_INFORMATION()
        kernel32.CreateProcessW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, ctypes.c_void_p, ctypes.c_void_p,
                                            wintypes.BOOL, wintypes.DWORD, ctypes.c_void_p, wintypes.LPCWSTR,
                                            ctypes.POINTER(STARTUPINFO), ctypes.POINTER(PROCESS_INFORMATION)]
        buf = ctypes.create_unicode_buffer(command)
        if not kernel32.CreateProcessW(None, buf, None, None, False, 0x08000000, None, None,
                                       ctypes.byref(si), ctypes.byref(pi)):
            raise ctypes.WinError(ctypes.get_last_error())
        kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        if kernel32.WaitForSingleObject(pi.hProcess, timeout * 1000) != 0:
            kernel32.TerminateProcess(pi.hProcess, 99)
            print('timeout: process terminated')
        code = wintypes.DWORD()
        kernel32.GetExitCodeProcess(pi.hProcess, ctypes.byref(code))
        kernel32.CloseHandle(pi.hThread)
        kernel32.CloseHandle(pi.hProcess)
        print('exit code', code.value)
        return 0 if code.value == 0 else 1
    finally:
        user32.CloseDesktop(desk)


if __name__ == '__main__':
    sys.exit(main())
