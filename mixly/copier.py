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


def _apply_attributes(path, info):
    attributes = info.st_file_attributes & KEPT_ATTRIBUTES
    if attributes:
        ctypes.windll.kernel32.SetFileAttributesW(path, attributes)


def _restore_stat(path, info):
    os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns))
    _apply_attributes(path, info)


def _copy_file(source, target, info, on_bytes, cancel):
    digest = hashlib.blake2b(digest_size=16)
    with open(source, "rb") as reader, open(target, "xb") as writer:
        while True:
            if cancel is not None and cancel.is_set():
                raise Cancelled()
            chunk = reader.read(CHUNK)
            if not chunk:
                break
            writer.write(chunk)
            digest.update(chunk)
            if on_bytes is not None:
                on_bytes(len(chunk))
    _restore_stat(target, info)
    return digest.hexdigest()


def _create_junction_allowing_missing_target(resolved, link, source_path):
    if os.path.exists(resolved):
        create_junction(resolved, link)
        return
    try:
        os.mkdir(resolved)
    except OSError as error:
        raise CopyError(f"{source_path} points to {resolved}, which can't be reached: {error}") from error
    try:
        create_junction(resolved, link)
    finally:
        os.rmdir(resolved)


def _copy_link(source_path, target_path, source_root, target_root, kind, info):
    value = os.readlink(source_path)
    clean = strip_extended(value)
    if os.path.isabs(clean):
        resolved = rebase(clean, source_root, target_root) if is_within(clean, source_root) else clean
    else:
        resolved = value
    if kind == "junction":
        _create_junction_allowing_missing_target(resolved, strip_extended(target_path), source_path)
    else:
        is_dir = bool(info.st_file_attributes & FILE_ATTRIBUTE_DIRECTORY)
        try:
            os.symlink(resolved, target_path, target_is_directory=is_dir)
        except OSError as error:
            raise CopyError(f"couldn't recreate the link {source_path}: {error}") from error
    return resolved
