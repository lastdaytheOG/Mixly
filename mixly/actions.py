from . import caches, known, launchers, mover, store_apps, volumes, wsl
from .copier import CopyError
from .journal import Busy
from .links import is_junction
from .services import ServiceError

ERRORS = (mover.MoveError, wsl.WslError, CopyError, ServiceError, OSError, Busy, KeyError)
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
    return mover.undo(record["id"], journal, store, progress, cancel)


def finish_record(record, journal, remove_pointer=False):
    kind = record["kind"]
    if kind in ("wsl", "store"):
        record["state"] = "finished"
        journal.put(record)
        return record
    if kind == "known":
        return known.finish(record["id"], journal)
    if kind == "native":
        return launchers.finish(record["id"], journal)
    return mover.finish(record["id"], journal, remove_pointer and mover.can_remove_pointer(record))


def recover(journal, store):
    return mover.recover(journal, store) + known.recover(journal) + launchers.recover(journal)


def clear_cache(found):
    freed, skipped = caches.clear(found.cache)
    message = f"Cleared {found.name} and freed {volumes.format_size(freed)}."
    if skipped:
        message += f" {skipped} items were in use and stayed."
    return message
