import ctypes
import os
from ctypes import wintypes

from .links import remove_tree
from .paths import full

FO_DELETE = 3
FOF_SILENT = 0x0004
FOF_NOCONFIRMATION = 0x0010
FOF_ALLOWUNDO = 0x0040
FOF_NOERRORUI = 0x0400
FOF_WANTNUKEWARNING = 0x4000
LIMIT = 259


class _Operation(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("wFunc", wintypes.UINT),
        ("pFrom", ctypes.c_void_p),
        ("pTo", wintypes.LPCWSTR),
        ("fFlags", wintypes.WORD),
        ("fAnyOperationsAborted", wintypes.BOOL),
        ("hNameMappings", ctypes.c_void_p),
        ("lpszProgressTitle", wintypes.LPCWSTR),
    ]


def to_recycle_bin(path):
    clean = full(path)
    if len(clean) > LIMIT:
        raise OSError(f"{os.path.basename(clean)} has too long a path for the Recycle Bin")
    buffer = ctypes.create_unicode_buffer(clean + "\0\0", len(clean) + 2)
    operation = _Operation()
    operation.wFunc = FO_DELETE
    operation.pFrom = ctypes.addressof(buffer)
    operation.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI | FOF_WANTNUKEWARNING
    shell = ctypes.WinDLL("shell32")
    shell.SHFileOperationW.argtypes = [ctypes.POINTER(_Operation)]
    shell.SHFileOperationW.restype = ctypes.c_int
    result = shell.SHFileOperationW(ctypes.byref(operation))
    if operation.fAnyOperationsAborted:
        raise OSError(f"deleting {os.path.basename(clean)} was cancelled")
    if result != 0:
        raise OSError(f"Windows couldn't delete {os.path.basename(clean)} (code {result:#x}). It may be in use")


def delete_permanently(path):
    remove_tree(full(path))
