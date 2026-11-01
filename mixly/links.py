import _winapi
import os
import stat

from .paths import long_path, strip_extended


def reparse_tag(path):
    try:
        return os.lstat(long_path(path)).st_reparse_tag
    except OSError:
        return 0


def is_junction(path):
    return reparse_tag(path) == stat.IO_REPARSE_TAG_MOUNT_POINT


def is_symlink(path):
    return reparse_tag(path) == stat.IO_REPARSE_TAG_SYMLINK


def link_target(path):
    return strip_extended(os.readlink(long_path(path)))


def create_junction(target, link):
    _winapi.CreateJunction(os.path.abspath(target), os.path.abspath(link))


def remove_junction(link):
    if not is_junction(link):
        raise ValueError(f"{link} is not a junction")
    os.rmdir(long_path(link))


def remove_tree(path):
    root = long_path(path)
    try:
        info = os.lstat(root)
    except FileNotFoundError:
        return
    _remove(root, info)


def _remove(path, info):
    tag = info.st_reparse_tag
    if tag == stat.IO_REPARSE_TAG_MOUNT_POINT:
        os.rmdir(path)
    elif tag == stat.IO_REPARSE_TAG_SYMLINK:
        os.unlink(path)
    elif stat.S_ISDIR(info.st_mode):
        with os.scandir(path) as entries:
            children = [entry.path for entry in entries]
        for child in children:
            _remove(child, os.lstat(child))
        os.chmod(path, stat.S_IWRITE)
        os.rmdir(path)
    else:
        os.chmod(path, stat.S_IWRITE)
        os.unlink(path)


def prune_empty(path, stop):
    current = os.path.dirname(os.path.abspath(path))
    limit = os.path.normcase(os.path.abspath(stop))
    while os.path.normcase(current).startswith(limit) and os.path.normcase(current) != limit:
        try:
            os.rmdir(long_path(current))
        except OSError:
            return
        current = os.path.dirname(current)
