from . import mover, wsl


def move_found(found, root, journal, store, progress=None, cancel=None):
    if found.distro:
        return wsl.move(found.distro, root, journal)
    return mover.move(found.source, root, journal, store, found.tool, progress, cancel)


def undo_record(record, journal, store, progress=None, cancel=None):
    if record["kind"] == "wsl":
        wsl.undo(record["id"], journal)
        return f"{record['name']} is back where it started."
    return mover.undo(record["id"], journal, store, progress, cancel)


def finish_record(record, journal, remove_pointer=False):
    if record["kind"] == "wsl":
        record["state"] = "finished"
        journal.put(record)
        return record
    return mover.finish(record["id"], journal, remove_pointer and mover.can_remove_pointer(record))
