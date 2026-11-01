import os
import subprocess

from . import caches, content, known, launchers, mover, store_apps, trash, volumes, wsl
from .copier import CopyError
from .journal import Busy
from .links import is_junction
from .services import ServiceError

ERRORS = (mover.MoveError, wsl.WslError, CopyError, ServiceError, OSError, Busy, KeyError)
SETTINGS_APPS = "ms-settings:appsfeatures"
NO_LIBRARY_NOTE = (
    "{name} moved with a link because Steam has no library on {drive}. "
    "Add one in Steam under Settings > Storage for a move that also avoids Steam's free space check."
)


def _move_game(found, root, journal, store, progress, cancel):
    tool = found.tool
    if tool.id.startswith(launchers.STEAM_PREFIX):
        drive = volumes.drive_of(root)
        library = launchers.steam_library_on(drive)
        if library:
            return launchers.move_steam(tool, library, journal, progress, cancel)
        record = mover.move(found.source, root, journal, store, tool, progress, cancel)
        record["note"] = NO_LIBRARY_NOTE.format(name=found.name, drive=drive)
        return record
    if tool.id.startswith(launchers.EPIC_PREFIX):
        return launchers.move_epic(tool, root, journal, progress, cancel)
    return mover.move(found.source, root, journal, store, tool, progress, cancel)


def move_found(found, root, journal, store, progress=None, cancel=None):
    if found.distro:
        record = wsl.move(found.distro, root, journal)
    elif found.is_item:
        record = content.move_item(found.source, root, journal, progress, cancel)
    elif found.known:
        record = known.move(found.known, root, journal, None, progress, cancel)
    elif found.package:
        record = store_apps.move(found.package, found.name, root, journal)
    elif found.tool is not None:
        record = _move_game(found, root, journal, store, progress, cancel)
    else:
        record = mover.move(found.source, root, journal, store, None, progress, cancel)
    record["category"] = found.category
    journal.put(record)
    return record


def undo_record(record, journal, store, progress=None, cancel=None):
    kind = record["kind"]
    if kind == "wsl":
        wsl.undo(record["id"], journal)
        return f"{record['name']} is back where it started."
    if kind == "known":
        return known.undo(record["id"], journal, None, progress, cancel)
    if kind == "native":
        return launchers.undo(record["id"], journal, progress, cancel)
    if kind == "store":
        return store_apps.undo(record["id"], journal)
    if kind == "content":
        return content.undo(record["id"], journal, progress, cancel)
    return mover.undo(record["id"], journal, store, progress, cancel)


def relocate(found, record, root, journal, store, progress=None, cancel=None):
    original = volumes.drive_of(record["source"])
    message = undo_record(record, journal, store, progress, cancel)
    if volumes.drive_of(root) == original:
        return message
    found.status = "ready"
    moved = move_found(found, root, journal, store, progress, cancel)
    return f"{found.name} moved to {moved['target']}."


def finish_record(record, journal, remove_pointer=False):
    kind = record["kind"]
    if kind in ("wsl", "store", "content"):
        record["state"] = "finished"
        journal.put(record)
        return record
    if kind == "known":
        return known.finish(record["id"], journal)
    if kind == "native":
        return launchers.finish(record["id"], journal)
    return mover.finish(record["id"], journal, remove_pointer and mover.can_remove_pointer(record))


def recover(journal, store):
    return mover.recover(journal, store) + known.recover(journal) + launchers.recover(journal) + content.recover(journal)


def clear_cache(found):
    freed, skipped = caches.clear(found.cache)
    message = f"Cleared {found.name} and freed {volumes.format_size(freed)}."
    if skipped:
        message += f" {skipped} items were in use and stayed."
    return message


def delete_found(found, journal, permanently=False):
    problem = content.problem_with(found.source, journal)
    if problem:
        raise mover.MoveError(problem)
    if permanently:
        trash.delete_permanently(found.source)
        return f"{found.name} was permanently deleted."
    trash.to_recycle_bin(found.source)
    return f"{found.name} is in the Recycle Bin. Empty it to get the space back."


def uninstall(found):
    tool = found.tool
    if found.package:
        os.startfile(SETTINGS_APPS)
        return f"Opened Windows Settings. Find {found.name} there to uninstall it."
    if tool is not None and tool.id.startswith(launchers.STEAM_PREFIX):
        os.startfile(f"steam://uninstall/{tool.id[len(launchers.STEAM_PREFIX):]}")
        return f"Asked Steam to uninstall {found.name}."
    if tool is not None and tool.uninstall:
        subprocess.Popen(tool.uninstall)
        return f"Opened the uninstaller for {found.name}."
    os.startfile(SETTINGS_APPS)
    return f"{found.name} has no uninstaller of its own, so Windows Settings is open."


def reveal(path):
    if os.path.exists(path):
        subprocess.Popen(["explorer", f"/select,{os.path.abspath(path)}"])
