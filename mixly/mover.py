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
