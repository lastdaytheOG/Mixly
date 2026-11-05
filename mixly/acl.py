import ctypes
import os
import re
from ctypes import wintypes

from .paths import is_within, key, long_path

DACL_SECURITY_INFORMATION = 0x4
SDDL_REVISION_1 = 1
LOCKED = "D:PAI(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;0x1200a9;;;BU)"
ACE = re.compile(r"\(([^;()]*);([^;()]*);")

_advapi = ctypes.WinDLL("advapi32", use_last_error=True)
_kernel = ctypes.WinDLL("kernel32", use_last_error=True)

_advapi.GetFileSecurityW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, wintypes.LPDWORD]
_advapi.GetFileSecurityW.restype = wintypes.BOOL
_advapi.SetFileSecurityW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p]
_advapi.SetFileSecurityW.restype = wintypes.BOOL
_advapi.ConvertSecurityDescriptorToStringSecurityDescriptorW.argtypes = [
    ctypes.c_void_p,
    wintypes.DWORD,
    wintypes.DWORD,
    ctypes.POINTER(wintypes.LPWSTR),
    wintypes.LPDWORD,
]
_advapi.ConvertSecurityDescriptorToStringSecurityDescriptorW.restype = wintypes.BOOL
_advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
    wintypes.LPCWSTR,
    wintypes.DWORD,
    ctypes.POINTER(ctypes.c_void_p),
    wintypes.LPDWORD,
]
_advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = wintypes.BOOL
_kernel.LocalFree.argtypes = [ctypes.c_void_p]
_kernel.LocalFree.restype = ctypes.c_void_p


def _fail():
    raise ctypes.WinError(ctypes.get_last_error())


def read_dacl(path):
    target = long_path(path)
    needed = wintypes.DWORD()
    _advapi.GetFileSecurityW(target, DACL_SECURITY_INFORMATION, None, 0, ctypes.byref(needed))
    if not needed.value:
        _fail()
    buffer = ctypes.create_string_buffer(needed.value)
    if not _advapi.GetFileSecurityW(target, DACL_SECURITY_INFORMATION, buffer, needed, ctypes.byref(needed)):
        _fail()
    text = wintypes.LPWSTR()
    converted = _advapi.ConvertSecurityDescriptorToStringSecurityDescriptorW(
        buffer, SDDL_REVISION_1, DACL_SECURITY_INFORMATION, ctypes.byref(text), None
    )
    if not converted:
        _fail()
    try:
        return text.value
    finally:
        _kernel.LocalFree(text)


def _strip_inherited(match):
    pairs = [match.group(2)[index:index + 2] for index in range(0, len(match.group(2)), 2)]
    return f"({match.group(1)};{''.join(pair for pair in pairs if pair != 'ID')};"


def standalone(sddl):
    start = sddl.find("(")
    if start < 0:
        return None
    return "D:PAI" + ACE.sub(_strip_inherited, sddl[start:])


def write_dacl(path, sddl):
    descriptor = ctypes.c_void_p()
    converted = _advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW(
        sddl, SDDL_REVISION_1, ctypes.byref(descriptor), None
    )
    if not converted:
        _fail()
    try:
        if not _advapi.SetFileSecurityW(long_path(path), DACL_SECURITY_INFORMATION, descriptor):
            _fail()
    finally:
        _kernel.LocalFree(descriptor)


def lock_chain(top, folder):
    if not is_within(folder, top) or os.path.dirname(os.path.abspath(top)) == os.path.abspath(top):
        raise ValueError(f"{folder} can't be locked from {top}")
    os.makedirs(long_path(folder), exist_ok=True)
    current = os.path.abspath(folder)
    limit = key(top)
    while True:
        write_dacl(current, LOCKED)
        if key(current) == limit:
            return
        current = os.path.dirname(current)


def copy_root_permissions(source, target):
    try:
        sddl = standalone(read_dacl(source))
        if sddl is not None:
            write_dacl(target, sddl)
    except OSError:
        pass
