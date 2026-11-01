import os
import stat
from dataclasses import dataclass, field

from . import services
from .copier import Cancelled
from .paths import key, long_path, protected_reason, strip_extended
from .scan import LARGE, STAYS, Found

GIGABYTE = 1024 ** 3


@dataclass
class Node:
    path: str
    size: int = 0
    children: list = field(default_factory=list)
    files: list = field(default_factory=list)


def _is_reparse(info):
    return bool(info.st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def read_tree(path, minimum, on_folder=None, cancel=None):
    node = Node(os.path.abspath(path))
    if cancel is not None and cancel.is_set():
        raise Cancelled()
    if on_folder is not None:
        on_folder(node.path)
    try:
        entries = list(os.scandir(long_path(path)))
    except OSError:
        return node
    for entry in entries:
        try:
            info = entry.stat(follow_symlinks=False)
        except OSError:
            continue
        if _is_reparse(info) and stat.S_ISDIR(info.st_mode):
            continue
        if stat.S_ISDIR(info.st_mode):
            child = read_tree(strip_extended(entry.path), minimum, on_folder, cancel)
            node.size += child.size
            if child.size >= minimum:
                node.children.append(child)
        else:
            node.size += info.st_size
            if info.st_size >= minimum:
                node.files.append((strip_extended(entry.path), info.st_size))
    return node


def container_keys():
    home = os.environ.get("USERPROFILE", "")
    local = os.environ.get("LOCALAPPDATA", "")
    names = ("Documents", "Downloads", "Desktop", "Pictures", "Music", "Videos", ".cache", ".local", ".gemini")
    keys = {key(os.path.join(home, name)) for name in names}
    keys.add(key(os.path.join(local, "Programs")))
    return keys


def stays_reason(path):
    reason = protected_reason(path)
    if reason:
        return reason
    temporary = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Temp")
    if key(path) == key(temporary):
        return "Windows and apps keep temporary files here"
    return None


def _has_movable(node):
    return stays_reason(node.path) is None or any(_has_movable(child) for child in node.children)


def pick(node, minimum, results=None, containers=None):
    chosen = [] if results is None else results
    groups = container_keys() if containers is None else containers
    reason = stays_reason(node.path)
    if reason:
        if any(_has_movable(child) for child in node.children):
            for child in node.children:
                pick(child, minimum, chosen, groups)
        elif node.size >= minimum:
            chosen.append((node.path, node.size, reason))
        return chosen
    if key(node.path) in groups and node.children:
        for child in node.children:
            pick(child, minimum, chosen, groups)
        return chosen
    chosen.append((node.path, node.size, ""))
    return chosen
