import os
import stat
from dataclasses import dataclass

from . import known, volumes
from .paths import long_path, strip_extended


@dataclass(frozen=True)
class Entry:
    name: str
    path: str
    is_folder: bool
    size: int
    modified: float


def list_folder(path):
    entries = []
    with os.scandir(long_path(path)) as listing:
        for item in listing:
            try:
                info = item.stat(follow_symlinks=False)
            except OSError:
                continue
            attributes = info.st_file_attributes
            if attributes & stat.FILE_ATTRIBUTE_SYSTEM and attributes & stat.FILE_ATTRIBUTE_HIDDEN:
                continue
            if attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT and not stat.S_ISREG(info.st_mode):
                continue
            is_folder = stat.S_ISDIR(info.st_mode)
            entries.append(Entry(item.name, strip_extended(item.path), is_folder, 0 if is_folder else info.st_size, info.st_mtime))
    return sorted(entries, key=lambda entry: (not entry.is_folder, entry.name.lower()))


def places():
    found = []
    for name, (label, _) in known.FOLDERS.items():
        try:
            found.append((label, known.current_path(name)))
        except OSError:
            continue
    for drive in volumes.list_drives(include_removable=True):
        found.append((f"{drive.letter}:", drive.root))
    return found


def parent_of(path):
    clean = os.path.abspath(path)
    parent = os.path.dirname(clean)
    return None if parent == clean else parent
