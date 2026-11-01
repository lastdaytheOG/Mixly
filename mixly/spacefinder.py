import os
import stat
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from . import services
from .copier import Cancelled
from .paths import key, long_path, protected_reason, strip_extended
from .scan import LARGE, STAYS, Found

GIGABYTE = 1024 ** 3
SPLIT_DEPTH = 3
WORKERS = 8


@dataclass
class Node:
    path: str
    size: int = 0
    children: list = field(default_factory=list)
    files: list = field(default_factory=list)
    waiting: list = field(default_factory=list)


def _is_reparse(info):
    return bool(info.st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def _read(path, minimum, on_folder, cancel, depth, pool):
    node = Node(os.path.abspath(path))
    if cancel is not None and cancel.is_set():
        raise Cancelled()
    if on_folder is not None:
        on_folder(node.path)
    try:
        entries = list(os.scandir(long_path(path)))
    except OSError:
        return node
    waiting = []
    for entry in entries:
        try:
            info = entry.stat(follow_symlinks=False)
        except OSError:
            continue
        if _is_reparse(info) and stat.S_ISDIR(info.st_mode):
            continue
        if stat.S_ISDIR(info.st_mode):
            folder = strip_extended(entry.path)
            if pool is None:
                _attach(node, _read(folder, minimum, on_folder, cancel, depth + 1, None), minimum)
            elif depth + 1 >= SPLIT_DEPTH:
                waiting.append(pool.submit(_read, folder, minimum, on_folder, cancel, depth + 1, None))
            else:
                waiting.append(_read(folder, minimum, on_folder, cancel, depth + 1, pool))
        else:
            node.size += info.st_size
            if info.st_size >= minimum:
                node.files.append((strip_extended(entry.path), info.st_size))
    node.waiting = waiting
    return node


def _attach(node, child, minimum):
    node.size += child.size
    if child.size >= minimum:
        node.children.append(child)


def _resolve(node, minimum):
    for item in node.waiting:
        child = item.result() if hasattr(item, "result") else item
        _resolve(child, minimum)
        _attach(node, child, minimum)
    node.waiting = []


def read_tree(path, minimum, on_folder=None, cancel=None):
    with ThreadPoolExecutor(WORKERS) as pool:
        try:
            node = _read(path, minimum, on_folder, cancel, 0, pool)
            _resolve(node, minimum)
        except Cancelled:
            pool.shutdown(wait=True, cancel_futures=True)
            raise
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


def find(root, journal, minimum=GIGABYTE, listing=None, on_folder=None, cancel=None):
    tree = read_tree(root, minimum, on_folder, cancel)
    available = services.list_services() if listing is None else listing
    states = {record["source"].lower(): record["state"] for record in journal.records()}
    found = []
    for path, size, reason in sorted(pick(tree, minimum), key=lambda entry: -entry[1]):
        drivers = [service for service in services.in_folder(path, available) if service.must_stay]
        if drivers and not reason:
            reason = f"Windows needs {drivers[0].name} early in startup"
        status = STAYS if reason else "ready"
        if path.lower() in states:
            status = "paused" if states[path.lower()] == "paused" else "moved"
        found.append(Found(path, os.path.basename(path) or path, path, size, status, category=LARGE, reason=reason))
    for path, size in sorted(tree.files, key=lambda entry: -entry[1]):
        found.append(Found(path, os.path.basename(path), path, size, STAYS, category=LARGE, reason="Windows needs this file on its own drive"))
    return found
