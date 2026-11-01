import ctypes
import hashlib
import os
import stat
from dataclasses import dataclass

from .links import create_junction
from .paths import is_within, long_path, rebase, strip_extended

CHUNK = 1024 * 1024
FILE_ATTRIBUTE_DIRECTORY = 0x10
KEPT_ATTRIBUTES = 0x1 | 0x2 | 0x4 | 0x20 | 0x2000


class CopyError(Exception):
    pass


class Cancelled(Exception):
    pass


@dataclass
class Item:
    kind: str
    size: int = 0
    digest: str = ""
    mtime: int = 0
    link: str = ""


def kind_of(info):
    tag = info.st_reparse_tag
    if tag == stat.IO_REPARSE_TAG_MOUNT_POINT:
        return "junction"
    if tag == stat.IO_REPARSE_TAG_SYMLINK:
        return "symlink"
    if tag == stat.IO_REPARSE_TAG_APPEXECLINK:
        return "other"
    if stat.S_ISDIR(info.st_mode):
        return "dir"
    if stat.S_ISREG(info.st_mode):
        return "file"
    return "other"


def walk(root):
    base = long_path(root)
    stack = [""]
    while stack:
        relative = stack.pop()
        folder = os.path.join(base, relative) if relative else base
        with os.scandir(folder) as entries:
            names = [entry.name for entry in entries]
        for name in names:
            child = os.path.join(relative, name) if relative else name
            info = os.lstat(os.path.join(base, child))
            kind = kind_of(info)
            if kind == "dir":
                stack.append(child)
            yield child, kind, info


def measure(root):
    size = files = 0
    unsupported = []
    for relative, kind, info in walk(root):
        if kind == "file":
            size += info.st_size
            files += 1
        elif kind == "other":
            unsupported.append(relative)
    return size, files, unsupported
