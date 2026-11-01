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
