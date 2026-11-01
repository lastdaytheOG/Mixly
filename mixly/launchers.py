import glob
import json
import os
import shutil
import time
import winreg

from . import acl, elevation, games, preflight, processes, volumes
from .copier import Cancelled, measure
from .journal import new_id
from .links import prune_empty, remove_tree
from .mover import BACKUP_SUFFIX, MOVED_STATES, MoveError, RESTORE_SUFFIX, copy_and_verify
from .paths import key, long_path, normalize_root

STEAM_PREFIX = "steam:"
EPIC_PREFIX = "epic:"


def steam_root():
    return games._registry_value(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath")


def steam_library_on(drive, root=None):
    steam = root or steam_root()
    if not steam:
        return None
    for library in games.steam_libraries(steam):
        if volumes.drive_of(library) == drive.upper():
            return library
    return None


def steam_paths(tool, library):
    source = os.path.abspath(tool.source)
    common = os.path.dirname(source)
    steamapps = os.path.dirname(common)
    appid = tool.id[len(STEAM_PREFIX):]
    apps = os.path.join(library, "steamapps")
    folders = [(source, os.path.join(apps, "common", os.path.basename(source)))]
    workshop = os.path.join(steamapps, "workshop", "content", appid)
    if os.path.isdir(workshop):
        folders.append((workshop, os.path.join(apps, "workshop", "content", appid)))
    files = [(os.path.join(steamapps, f"appmanifest_{appid}.acf"), os.path.join(apps, f"appmanifest_{appid}.acf"))]
    workshop_file = os.path.join(steamapps, "workshop", f"appworkshop_{appid}.acf")
    if os.path.isfile(workshop_file):
        files.append((workshop_file, os.path.join(apps, "workshop", f"appworkshop_{appid}.acf")))
    return folders, files


def _replace_path(value, old, new):
    if isinstance(value, dict):
        return {name: _replace_path(item, old, new) for name, item in value.items()}
    if isinstance(value, list):
        return [_replace_path(item, old, new) for item in value]
    if isinstance(value, str):
        clean = value.replace("/", "\\").lower()
        prefix = old.replace("/", "\\").rstrip("\\").lower()
        if clean == prefix or clean.startswith(prefix + "\\"):
            return new + value[len(prefix):]
    return value


def rewrite_json(path, old, new):
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    updated = _replace_path(data, old, new)
    temporary = path + ".mixly-tmp"
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(updated, handle, indent=4)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def epic_manifests():
    return os.path.join(os.environ.get("ProgramData", r"C:\ProgramData"), "Epic", "EpicGamesLauncher", "Data", "Manifests")


def epic_launcher_file():
    return os.path.join(os.environ.get("ProgramData", r"C:\ProgramData"), "Epic", "UnrealEngineLauncher", "LauncherInstalled.dat")


def epic_files_for(source, manifests=None, launcher_file=None):
    found = []
    for item in glob.glob(os.path.join(glob.escape(manifests or epic_manifests()), "*.item")):
        try:
            with open(item, encoding="utf-8") as handle:
                values = json.load(handle)
        except (OSError, ValueError):
            continue
        if key(values.get("InstallLocation", "")) == key(source):
            found.append(item)
    if not found:
        raise MoveError(f"couldn't find Epic's record for {source}")
    dat = launcher_file or epic_launcher_file()
    if os.path.isfile(dat):
        found.append(dat)
    return found


def _record(tool, root, folders, files, rewrites, check):
    return {
        "id": new_id(),
        "kind": "native",
        "name": tool.name,
        "tool": tool.id,
        "source": folders[0][0],
        "target": folders[0][1],
        "backup": folders[0][0] + BACKUP_SUFFIX,
        "root": normalize_root(root),
        "bytes": check.size,
        "files": check.files,
        "created": int(time.time()),
        "pointer": False,
        "processes": list(tool.processes),
        "folders": [{"source": source, "target": target, "backup": source + BACKUP_SUFFIX} for source, target in folders],
        "plain_files": [{"source": source, "target": target, "backup": source + BACKUP_SUFFIX} for source, target in files],
        "rewrites": list(rewrites),
    }


def _paused(journal, source):
    for record in journal.records():
        if record.get("kind") == "native" and record["state"] == preflight.PAUSED and key(record["source"]) == key(source):
            return record
    return None


def _remove_targets(record):
    stop = normalize_root(record["root"])
    for pair in record["folders"] + record["plain_files"]:
        remove_tree(pair["target"])
        prune_empty(pair["target"], stop)


def _forward_rewrites(record):
    for path in record["rewrites"]:
        rewrite_json(path, record["source"], record["target"])


def _reverse_rewrites(record):
    for path in record["rewrites"]:
        rewrite_json(path, record["target"], record["source"])


def _copy_everything(record, progress, cancel, resume):
    for pair in record["folders"]:
        os.makedirs(long_path(os.path.dirname(pair["target"])), exist_ok=True)
        if record["tool"].startswith(EPIC_PREFIX) and elevation.is_admin():
            acl.lock_chain(os.path.dirname(pair["target"]), os.path.dirname(pair["target"]))
        size = measure(pair["source"])[0]
        copy_and_verify(pair["source"], pair["target"], size, progress, cancel, resume and os.path.isdir(pair["target"]))
    for pair in record["plain_files"]:
        os.makedirs(long_path(os.path.dirname(pair["target"])), exist_ok=True)
        shutil.copy2(long_path(pair["source"]), long_path(pair["target"]))


def _switch(record):
    _forward_rewrites(record)
    for pair in record["folders"] + record["plain_files"]:
        os.rename(long_path(pair["source"]), long_path(pair["backup"]))


def _unswitch(record, journal):
    for pair in record["folders"] + record["plain_files"]:
        if os.path.lexists(pair["backup"]) and not os.path.lexists(pair["source"]):
            os.rename(long_path(pair["backup"]), long_path(pair["source"]))
    _reverse_rewrites(record)
    _remove_targets(record)
    journal.remove(record["id"])


def relocate(tool, root, folders, files, rewrites, journal, progress=None, cancel=None, names=None, same_drive_ok=False):
    check = preflight.run(folders[0][0], root, journal, tool, same_drive_ok, names, folders[0][1])
    if check.problems:
        raise MoveError("; ".join(check.problems))
    paused = _paused(journal, folders[0][0])
    record = paused or _record(tool, root, folders, files, rewrites, check)
    record["state"] = "copying"
    journal.put(record)
    try:
        _copy_everything(record, progress, cancel, bool(paused))
    except Cancelled:
        record["state"] = preflight.PAUSED
        journal.put(record)
        raise
    except BaseException as error:
        _remove_targets(record)
        journal.remove(record["id"])
        if isinstance(error, OSError):
            raise MoveError(f"{record['name']}: {error}") from error
        raise
    record["state"] = "switching"
    journal.put(record)
    try:
        _switch(record)
    except BaseException as error:
        _unswitch(record, journal)
        if isinstance(error, OSError):
            raise MoveError(f"{record['name']} is in use, so nothing was changed: {error}") from error
        raise
    record["state"] = "moved"
    journal.put(record)
    return record


def move_steam(tool, library, journal, progress=None, cancel=None, names=None, same_drive_ok=False):
    folders, files = steam_paths(tool, library)
    return relocate(tool, library, folders, files, [], journal, progress, cancel, names, same_drive_ok)


def move_epic(tool, root, journal, progress=None, cancel=None, names=None, manifests=None, launcher_file=None, same_drive_ok=False):
    source = os.path.abspath(tool.source)
    target = os.path.join(normalize_root(root), "Epic Games", os.path.basename(source))
    rewrites = epic_files_for(source, manifests, launcher_file)
    return relocate(tool, root, [(source, target)], [], rewrites, journal, progress, cancel, names, same_drive_ok)


def finish(record_id, journal):
    record = journal.get(record_id)
    if record["state"] not in MOVED_STATES:
        raise MoveError(f"{record['name']} can't be finished from state {record['state']}")
    for pair in record["folders"]:
        if not os.path.isdir(pair["target"]):
            raise MoveError(f"{pair['target']} is missing")
    for pair in record["folders"] + record["plain_files"]:
        remove_tree(pair["backup"])
    record["state"] = "finished"
    journal.put(record)
    return record


def undo(record_id, journal, progress=None, cancel=None, names=None):
    record = journal.get(record_id)
    if record["state"] == preflight.PAUSED:
        _remove_targets(record)
        journal.remove(record["id"])
        return f"{record['name']}: the paused move was discarded, and nothing else changed."
    if record["state"] not in MOVED_STATES:
        raise MoveError(f"{record['name']} can't be undone from state {record['state']}")
    active = processes.still_running(record.get("processes", []), names)
    active += sorted({os.path.basename(path) for path in processes.running_from(record["target"])})
    if active:
        raise MoveError(f"close {', '.join(active)} first")
    needed = sum(measure(pair["target"])[0] for pair in record["folders"])
    if volumes.free_bytes(volumes.drive_of(record["source"])) < needed:
        raise MoveError(f"not enough free space on {volumes.drive_of(record['source'])}")
    restores = []
    try:
        for pair in record["folders"]:
            restore = pair["source"] + RESTORE_SUFFIX
            restores.append(restore)
            remove_tree(restore)
            copy_and_verify(pair["target"], restore, measure(pair["target"])[0], progress, cancel)
        for pair in record["plain_files"]:
            restore = pair["source"] + RESTORE_SUFFIX
            restores.append(restore)
            shutil.copy2(long_path(pair["target"]), long_path(restore))
    except BaseException:
        for restore in restores:
            remove_tree(restore)
        raise
    _complete_undo(record, journal)
    return f"{record['name']} is back where it started."


def _complete_undo(record, journal):
    record["previous_state"] = record["state"]
    record["state"] = "restoring"
    journal.put(record)
    for pair in record["folders"] + record["plain_files"]:
        restore = pair["source"] + RESTORE_SUFFIX
        if os.path.lexists(restore):
            os.rename(long_path(restore), long_path(pair["source"]))
    _reverse_rewrites(record)
    for pair in record["folders"] + record["plain_files"]:
        remove_tree(pair["backup"])
    _remove_targets(record)
    journal.remove(record["id"])


def recover(journal):
    messages = []
    for record in journal.records():
        if record.get("kind") != "native":
            continue
        if record["state"] == "copying":
            record["state"] = preflight.PAUSED
            journal.put(record)
            messages.append(f"{record['name']}: the move was interrupted. Move it again to continue from where it stopped")
        elif record["state"] == "switching":
            _unswitch(record, journal)
            messages.append(f"{record['name']}: the move was interrupted, so it was put back")
        elif record["state"] == "restoring":
            _complete_undo(record, journal)
            messages.append(f"{record['name']}: finished the interrupted undo")
    return messages
