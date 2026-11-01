import ctypes
import re
from ctypes import wintypes

from .paths import long_path

DACL_SECURITY_INFORMATION = 0x4
SDDL_REVISION_1 = 1
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
