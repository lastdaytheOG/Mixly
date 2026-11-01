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


def move_item(path, root, journal, progress=None, cancel=None, same_drive_ok=False):
    source = full(path)
    problem = problem_with(source, journal)
    if problem:
        raise MoveError(problem)
    normalized = normalize_root(root)
    drive = volumes.drive_of(normalized)
    if not same_drive_ok and drive == volumes.drive_of(source):
        raise MoveError(f"{os.path.basename(source)} is already on {drive}")
    size = _size_of(source)
    needed = needed_space(size)
    free = volumes.free_bytes(drive)
    if free < needed:
        raise MoveError(f"needs {volumes.format_size(needed)}, but only {volumes.format_size(free)} is free on {drive}")
    target = free_name(content_target(normalized, source))
    backup = source + BACKUP_SUFFIX
    record = {
        "id": new_id(),
        "kind": "content",
        "name": os.path.basename(source),
        "tool": None,
        "source": source,
        "target": target,
        "backup": backup,
        "root": normalized,
        "bytes": size,
        "files": 1,
        "created": int(time.time()),
        "pointer": False,
        "state": "copying",
    }
    journal.put(record)
    try:
        _copy(source, target, size, progress, cancel)
    except BaseException as error:
        _discard(record, journal)
        if isinstance(error, OSError):
            raise MoveError(f"{record['name']}: {error}") from error
        raise
    try:
        os.rename(long_path(source), long_path(backup))
    except OSError as error:
        _discard(record, journal)
        raise MoveError(f"{record['name']} is in use, so nothing was changed: {error}") from error
    record["state"] = "removing"
    journal.put(record)
    _finish_removal(record, journal)
    return record


def _discard(record, journal):
    remove_tree(record["target"])
    prune_empty(record["target"], normalize_root(record["root"]))
    journal.remove(record["id"])


def _finish_removal(record, journal):
    remove_tree(record["backup"])
    record["state"] = "finished"
    journal.put(record)


def undo(record_id, journal, progress=None, cancel=None):
    record = journal.get(record_id)
    target, source = record["target"], record["source"]
    if not os.path.lexists(target):
        journal.remove(record_id)
        return f"{record['name']} is no longer at {target}, so it was removed from this list."
    destination = free_name(source)
    size = _size_of(target)
    drive = volumes.drive_of(destination)
    if volumes.free_bytes(drive) < size:
        raise MoveError(f"not enough free space on {drive}")
    restore = destination + RESTORE_SUFFIX
    remove_tree(restore)
    try:
        _copy(target, restore, size, progress, cancel)
    except BaseException as error:
        remove_tree(restore)
        if isinstance(error, OSError):
            raise MoveError(f"{record['name']}: {error}") from error
        raise
    os.rename(long_path(restore), long_path(destination))
    try:
        _discard(record, journal)
    except OSError as error:
        raise MoveError(f"{record['name']} is back, but the copy at {target} couldn't be deleted: {error}") from error
    return f"{record['name']} is back in {os.path.dirname(destination)}."
