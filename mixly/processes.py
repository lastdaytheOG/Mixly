import csv
import ctypes
import io
import subprocess
from ctypes import wintypes

from .paths import is_within

CREATE_NO_WINDOW = 0x08000000
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

_kernel = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
_kernel.OpenProcess.restype = wintypes.HANDLE
_kernel.CloseHandle.argtypes = [wintypes.HANDLE]
_kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, wintypes.LPDWORD]
_kernel.K32EnumProcesses.argtypes = [ctypes.POINTER(wintypes.DWORD), wintypes.DWORD, wintypes.LPDWORD]


def image_paths():
    capacity = 8192
    ids = (wintypes.DWORD * capacity)()
    used = wintypes.DWORD()
    if not _kernel.K32EnumProcesses(ids, ctypes.sizeof(ids), ctypes.byref(used)):
        return []
    paths = []
    for process_id in ids[: used.value // ctypes.sizeof(wintypes.DWORD)]:
        handle = _kernel.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, process_id)
        if not handle:
            continue
        try:
            buffer = ctypes.create_unicode_buffer(32768)
            size = wintypes.DWORD(len(buffer))
            if _kernel.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
                paths.append(buffer.value)
        finally:
            _kernel.CloseHandle(handle)
    return paths


def running_from(folder):
    return sorted(path for path in image_paths() if is_within(path, folder))


def running_names():
    result = subprocess.run(
        ["tasklist", "/fo", "csv", "/nh"],
        capture_output=True,
        creationflags=CREATE_NO_WINDOW,
    )
    text = result.stdout.decode("oem", errors="replace")
    return {row[0].lower() for row in csv.reader(io.StringIO(text)) if row}


def still_running(wanted, names=None):
    active = running_names() if names is None else names
    return sorted(name for name in wanted if name.lower() in active)
