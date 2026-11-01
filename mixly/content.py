import os
import sys
import time

from . import known, processes, services, volumes
from .copier import Cancelled, copy_file_verified, copy_tree, measure, verify_tree
from .journal import new_id
from .links import is_junction, is_symlink, prune_empty, remove_tree
from .mover import BACKUP_SUFFIX, MoveError, RESTORE_SUFFIX
from .paths import full, is_within, long_path, normalize_root, protected_reason
from .preflight import needed_space


def known_folder_paths():
    found = []
    for name in known.FOLDERS:
        try:
            found.append(known.current_path(name))
        except OSError:
            continue
    return found


def problem_with(path, journal):
    source = full(path)
    if not os.path.lexists(source):
        return f"{source} doesn't exist"
    if is_junction(source) or is_symlink(source):
        return f"{os.path.basename(source)} is a link. Use Undo on the Moved page instead"
    reason = protected_reason(source)
    if reason:
        return reason
    for folder in known_folder_paths():
        if is_within(folder, source):
            return f"{source} is a Windows folder, so choose what's inside it instead"
    for own in (sys.executable, os.path.abspath(__file__), os.getcwd()):
        if is_within(own, source):
            return f"{source} is in use by Mixly itself"
    for record in journal.records():
        for known_path in (record.get("source"), record.get("target")):
            if known_path and record.get("kind") != "content" and (is_within(source, known_path) or is_within(known_path, source)):
                return f"{source} overlaps {known_path}, which Mixly moved"
    if os.path.isdir(source):
        found = services.in_folder(source)
        if found:
            return f"{source} runs the Windows service {found[0].name}"
        active = processes.running_from(source)
        if active:
            names = sorted({os.path.basename(item) for item in active})
            return f"close {', '.join(names)} first"
    return None


def content_target(root, source):
    base = normalize_root(root)
    clean = full(source)
    if os.path.dirname(base) == base:
        parent = os.path.basename(os.path.dirname(clean))
        return os.path.join(base, parent, os.path.basename(clean)) if parent else os.path.join(base, os.path.basename(clean))
    return os.path.join(base, os.path.basename(clean))


def free_name(path):
    if not os.path.lexists(path):
        return path
    stem, extension = os.path.splitext(path)
    number = 2
    while os.path.lexists(f"{stem} ({number}){extension}"):
        number += 1
    return f"{stem} ({number}){extension}"


def _size_of(path):
    return measure(path)[0] if os.path.isdir(path) else os.path.getsize(long_path(path))


def _progress_adapter(size, progress):
    total = max(size * 2, 1)
    done = [0]

    def advance(count):
        done[0] += count
        if progress is not None:
            progress(done[0], total)

    return advance


def _copy(source, target, size, progress, cancel):
    advance = _progress_adapter(size, progress)
    if os.path.isdir(source):
        manifest = copy_tree(source, target, advance, cancel)
        verify_tree(manifest, source, target, advance, cancel)
    else:
        copy_file_verified(source, target, advance, cancel)
