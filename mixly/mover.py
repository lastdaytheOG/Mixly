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
