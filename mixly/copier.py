import ctypes
import hashlib
import os
import stat
from dataclasses import dataclass

from .acl import copy_root_permissions
from .links import create_junction, remove_tree
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
    drivers = []
    for relative, kind, info in walk(root):
        if kind == "file":
            size += info.st_size
            files += 1
            if relative.lower().endswith(".sys"):
                drivers.append(relative)
        elif kind == "other":
            unsupported.append(relative)
    return size, files, unsupported, drivers


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


def _reuse_copied_file(source_path, target_path, info, on_bytes, cancel):
    try:
        existing = os.lstat(target_path)
    except FileNotFoundError:
        return None
    if kind_of(existing) == "file" and existing.st_size == info.st_size and existing.st_mtime_ns == info.st_mtime_ns:
        return _hash_file(source_path, on_bytes, cancel)
    remove_tree(target_path)
    return None


def copy_tree(source, target, on_bytes=None, cancel=None, resume=False):
    manifest = {}
    source_base, target_base = long_path(source), long_path(target)
    folders = [("", os.lstat(source_base))]
    links = []
    os.makedirs(target_base, exist_ok=resume)
    copy_root_permissions(source, target)
    for relative, kind, info in walk(source):
        if cancel is not None and cancel.is_set():
            raise Cancelled()
        source_path = os.path.join(source_base, relative)
        target_path = os.path.join(target_base, relative)
        if kind == "dir":
            os.makedirs(target_path, exist_ok=True)
            folders.append((relative, info))
            manifest[relative] = Item("dir")
        elif kind == "file":
            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            digest = _reuse_copied_file(source_path, target_path, info, on_bytes, cancel) if resume else None
            if digest is None:
                digest = _copy_file(source_path, target_path, info, on_bytes, cancel)
            manifest[relative] = Item("file", info.st_size, digest, info.st_mtime_ns)
        elif kind in ("junction", "symlink"):
            links.append((relative, kind, info))
        else:
            raise CopyError(f"{source_path} can't be copied")
    for relative, kind, info in links:
        source_path = os.path.join(source_base, relative)
        target_path = os.path.join(target_base, relative)
        os.makedirs(os.path.dirname(target_path), exist_ok=True)
        if resume and os.path.lexists(target_path):
            remove_tree(target_path)
        link = _copy_link(source_path, target_path, source, target, kind, info)
        manifest[relative] = Item(kind, link=link)
    for relative, info in sorted(folders, key=lambda folder: -len(folder[0])):
        path = os.path.join(target_base, relative) if relative else target_base
        _restore_stat(path, info)
    return manifest


def _hash_file(path, on_bytes, cancel):
    digest = hashlib.blake2b(digest_size=16)
    with open(path, "rb") as reader:
        while True:
            if cancel is not None and cancel.is_set():
                raise Cancelled()
            chunk = reader.read(CHUNK)
            if not chunk:
                return digest.hexdigest()
            digest.update(chunk)
            if on_bytes is not None:
                on_bytes(len(chunk))


def _check_source_unchanged(manifest, source):
    seen = set()
    for relative, kind, info in walk(source):
        seen.add(relative)
        item = manifest.get(relative)
        if item is None or item.kind != kind:
            raise CopyError(f"{relative} changed while it was being copied")
        if kind == "file" and (item.size != info.st_size or item.mtime != info.st_mtime_ns):
            raise CopyError(f"{relative} changed while it was being copied")
    missing = set(manifest) - seen
    if missing:
        raise CopyError(f"{sorted(missing)[0]} disappeared while it was being copied")


def _check_target(manifest, target, on_bytes, cancel):
    base = long_path(target)
    seen = set()
    for relative, kind, info in walk(target):
        seen.add(relative)
        item = manifest.get(relative)
        if item is None or item.kind != kind:
            raise CopyError(f"{relative} doesn't match the original")
        if kind == "file":
            if item.size != info.st_size:
                raise CopyError(f"{relative} has the wrong size")
            if _hash_file(os.path.join(base, relative), on_bytes, cancel) != item.digest:
                raise CopyError(f"{relative} failed its checksum")
    missing = set(manifest) - seen
    if missing:
        raise CopyError(f"{sorted(missing)[0]} is missing from the copy")


def verify_tree(manifest, source, target, on_bytes=None, cancel=None):
    _check_source_unchanged(manifest, source)
    _check_target(manifest, target, on_bytes, cancel)
