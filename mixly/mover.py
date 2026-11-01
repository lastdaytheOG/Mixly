import os
import time

from . import environment, preflight, processes, volumes
from .catalog import by_id
from .copier import copy_tree, measure, verify_tree
from .journal import new_id
from .links import create_junction, is_junction, link_target, prune_empty, remove_junction, remove_tree
from .paths import key, long_path, normalize_root

BACKUP_SUFFIX = ".mixly-old"
RESTORE_SUFFIX = ".mixly-restore"
FORWARD_STATES = ("copying", "copied", "swapped", "linked")
MOVED_STATES = ("moved", "finished")


class MoveError(Exception):
    pass


def _tool_of(record):
    if not record.get("tool"):
        return None
    try:
        return by_id(record["tool"])
    except KeyError:
        return None


def can_remove_pointer(record):
    tool = _tool_of(record)
    return tool is not None and tool.native


def _clear_target(record):
    remove_tree(record["target"])
    prune_empty(record["target"], normalize_root(record["root"]))


def _rollback(record, journal, store):
    if record.get("env_applied"):
        environment.restore_changes(store, record["env"], record["source"], record["target"])
    if is_junction(record["source"]):
        remove_junction(record["source"])
    if os.path.lexists(record["backup"]) and not os.path.lexists(record["source"]):
        os.rename(long_path(record["backup"]), long_path(record["source"]))
    _clear_target(record)
    journal.remove(record["id"])


def _copy_and_verify(source, target, size, progress, cancel):
    total = max(size * 2, 1)
    done = [0]

    def advance(count):
        done[0] += count
        if progress is not None:
            progress(done[0], total)

    manifest = copy_tree(source, target, advance, cancel)
    verify_tree(manifest, source, target, advance, cancel)


def move(source, root, journal, store, tool=None, progress=None, cancel=None, same_drive_ok=False, names=None):
    check = preflight.run(source, root, journal, tool, same_drive_ok, names)
    if check.problems:
        raise MoveError("; ".join(check.problems))
    record = {
        "id": new_id(),
        "kind": "folder",
        "name": tool.name if tool else os.path.basename(check.source),
        "tool": tool.id if tool else None,
        "source": check.source,
        "target": check.target,
        "backup": check.source + BACKUP_SUFFIX,
        "root": check.root,
        "bytes": check.size,
        "files": check.files,
        "created": int(time.time()),
        "pointer": True,
        "processes": list(tool.processes) if tool else [],
        "state": "copying",
    }
    journal.put(record)
    try:
        _copy_and_verify(check.source, check.target, check.size, progress, cancel)
    except BaseException as error:
        _clear_target(record)
        journal.remove(record["id"])
        if isinstance(error, OSError):
            raise MoveError(f"{record['name']}: {error}") from error
        raise
    record["state"] = "copied"
    journal.put(record)
    try:
        os.rename(long_path(check.source), long_path(record["backup"]))
    except OSError as error:
        _clear_target(record)
        journal.remove(record["id"])
        raise MoveError(f"{record['name']} is in use, so nothing was changed: {error}") from error
    record["state"] = "swapped"
    journal.put(record)
    try:
        create_junction(check.target, check.source)
        record["state"] = "linked"
        journal.put(record)
        if sorted(os.listdir(long_path(check.source))) != sorted(os.listdir(long_path(check.target))):
            raise MoveError(f"the link at {check.source} doesn't show the moved files")
        record["env"] = environment.plan_changes(store, check.source, check.target, tool.env if tool else ())
        record["env_applied"] = True
        journal.put(record)
        environment.apply_changes(store, record["env"], check.source, check.target)
    except BaseException:
        _rollback(record, journal, store)
        raise
    record["state"] = "moved"
    journal.put(record)
    return record


def finish(record_id, journal, remove_pointer=False):
    record = journal.get(record_id)
    if record["kind"] != "folder" or record["state"] not in MOVED_STATES:
        raise MoveError(f"{record['name']} can't be finished from state {record['state']}")
    if not os.path.isdir(record["target"]):
        raise MoveError(f"{record['target']} is missing")
    if record["pointer"]:
        if not is_junction(record["source"]) or key(link_target(record["source"])) != key(record["target"]):
            raise MoveError(f"{record['source']} no longer points to {record['target']}")
    if remove_pointer and record["pointer"] and not can_remove_pointer(record):
        raise MoveError(f"{record['name']} needs its link to keep working")
    remove_tree(record["backup"])
    if remove_pointer and record["pointer"]:
        remove_junction(record["source"])
        record["pointer"] = False
    record["state"] = "finished"
    journal.put(record)
    return record


def undo(record_id, journal, store, progress=None, cancel=None, names=None):
    record = journal.get(record_id)
    if record["kind"] != "folder" or record["state"] not in MOVED_STATES:
        raise MoveError(f"{record['name']} can't be undone from state {record['state']}")
    if not os.path.isdir(record["target"]):
        return _forget_removed(record, journal, store)
    active = processes.still_running(record.get("processes", []), names)
    active += sorted({os.path.basename(path) for path in processes.running_from(record["target"])})
    if active:
        raise MoveError(f"close {', '.join(active)} first")
    size = measure(record["target"])[0]
    if volumes.free_bytes(volumes.drive_of(record["source"])) < size:
        raise MoveError(f"not enough free space on {volumes.drive_of(record['source'])}")
    restore = record["source"] + RESTORE_SUFFIX
    if os.path.lexists(restore):
        remove_tree(restore)
    record["previous_state"] = record["state"]
    record["state"] = "restoring"
    journal.put(record)
    try:
        _copy_and_verify(record["target"], restore, size, progress, cancel)
    except BaseException as error:
        remove_tree(restore)
        record["state"] = record.pop("previous_state")
        journal.put(record)
        if isinstance(error, OSError):
            raise MoveError(f"{record['name']}: {error}") from error
        raise
    _complete_undo(record, journal, store)
    return f"{record['name']} is back where it started."


def _forget_removed(record, journal, store):
    drive = volumes.drive_of(record["target"])
    if not os.path.exists(f"{drive}\\"):
        raise MoveError(f"{drive} isn't connected, so {record['name']} can't be undone yet")
    if record.get("env_applied"):
        environment.restore_changes(store, record["env"], record["source"], record["target"])
    if is_junction(record["source"]):
        remove_junction(record["source"])
    restored = os.path.lexists(record["backup"]) and not os.path.lexists(record["source"])
    if restored:
        os.rename(long_path(record["backup"]), long_path(record["source"]))
    journal.remove(record["id"])
    if restored:
        return f"{record['name']} was missing from {record['target']}, so the old copy was put back."
    return f"{record['name']} was already gone from {record['target']}, so its link was removed."


def _complete_undo(record, journal, store):
    restore = record["source"] + RESTORE_SUFFIX
    if is_junction(record["source"]):
        remove_junction(record["source"])
    os.rename(long_path(restore), long_path(record["source"]))
    if record.get("env_applied"):
        environment.restore_changes(store, record["env"], record["source"], record["target"])
    remove_tree(record["backup"])
    _clear_target(record)
    journal.remove(record["id"])


def _recover_restoring(record, journal, store):
    restore = record["source"] + RESTORE_SUFFIX
    if is_junction(record["source"]):
        remove_tree(restore)
        record["state"] = record.pop("previous_state")
        journal.put(record)
        return f"{record['name']}: the undo was interrupted, so it stays moved"
    if not os.path.lexists(record["source"]) and os.path.isdir(restore) and not record.get("pointer"):
        remove_tree(restore)
        record["state"] = record.pop("previous_state")
        journal.put(record)
        return f"{record['name']}: the undo was interrupted, so it stays moved"
    if not os.path.lexists(record["source"]) and not os.path.isdir(restore):
        create_junction(record["target"], record["source"])
        record["state"] = record.pop("previous_state")
        journal.put(record)
        return f"{record['name']}: the undo was interrupted, so it stays moved"
    if not os.path.lexists(record["source"]):
        os.rename(long_path(restore), long_path(record["source"]))
    if record.get("env_applied"):
        environment.restore_changes(store, record["env"], record["source"], record["target"])
    remove_tree(record["backup"])
    _clear_target(record)
    journal.remove(record["id"])
    return f"{record['name']}: finished the interrupted undo"


def recover(journal, store):
    messages = []
    for record in journal.records():
        if record.get("kind") != "folder":
            continue
        if record["state"] in FORWARD_STATES:
            _rollback(record, journal, store)
            messages.append(f"{record['name']}: the move was interrupted, so it was put back")
        elif record["state"] == "restoring":
            messages.append(_recover_restoring(record, journal, store))
    return messages
