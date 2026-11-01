import ctypes
import os
import time
import uuid
from ctypes import wintypes

from . import preflight, processes, volumes
from .copier import measure
from .journal import new_id
from .links import prune_empty, remove_tree
from .mover import MoveError, RESTORE_SUFFIX, copy_and_verify, lock_destination
from .paths import key, long_path, normalize_root

SHCNE_ASSOCCHANGED = 0x08000000
FOLDERS = {
    "downloads": ("Downloads", "374DE290-123F-4565-9164-39C4925E467B"),
    "documents": ("Documents", "FDD39AD0-238F-46AF-ADB4-6C85480369C7"),
    "desktop": ("Desktop", "B4BFCC3A-DB2C-424C-B029-7FE99A87C641"),
    "pictures": ("Pictures", "33E28130-4E1E-4676-835A-98395C3BC3BB"),
    "music": ("Music", "4BD8D571-6D19-48D3-BE97-422220080E43"),
    "videos": ("Videos", "18989B1D-99B5-455B-841C-AB7C74E4DDFC"),
}
CONTACTS = "56784854-C6CB-462B-8169-88E350ACB882"


class _Guid(ctypes.Structure):
    _fields_ = [("data", ctypes.c_ubyte * 16)]


def _guid(text):
    value = _Guid()
    ctypes.memmove(value.data, uuid.UUID(text).bytes_le, 16)
    return value


class WindowsFolders:
    def get(self, folder_id):
        shell = ctypes.WinDLL("shell32")
        ole = ctypes.WinDLL("ole32")
        shell.SHGetKnownFolderPath.argtypes = [ctypes.POINTER(_Guid), wintypes.DWORD, wintypes.HANDLE, ctypes.POINTER(wintypes.LPWSTR)]
        shell.SHGetKnownFolderPath.restype = ctypes.c_long
        ole.CoTaskMemFree.argtypes = [ctypes.c_void_p]
        guid = _guid(folder_id)
        text = wintypes.LPWSTR()
        result = shell.SHGetKnownFolderPath(ctypes.byref(guid), 0, None, ctypes.byref(text))
        try:
            if result != 0:
                raise OSError(f"couldn't read the folder location ({result & 0xFFFFFFFF:#x})")
            return text.value
        finally:
            ole.CoTaskMemFree(text)

    def set(self, folder_id, path):
        shell = ctypes.WinDLL("shell32")
        shell.SHSetKnownFolderPath.argtypes = [ctypes.POINTER(_Guid), wintypes.DWORD, wintypes.HANDLE, wintypes.LPCWSTR]
        shell.SHSetKnownFolderPath.restype = ctypes.c_long
        shell.SHChangeNotify.argtypes = [ctypes.c_long, wintypes.UINT, ctypes.c_void_p, ctypes.c_void_p]
        shell.SHChangeNotify.restype = None
        guid = _guid(folder_id)
        result = shell.SHSetKnownFolderPath(ctypes.byref(guid), 0, None, path)
        if result != 0:
            raise OSError(f"Windows refused the new folder location ({result & 0xFFFFFFFF:#x})")
        shell.SHChangeNotify(SHCNE_ASSOCCHANGED, 0, None, None)


def _folder_id(name):
    return FOLDERS[name][1] if name in FOLDERS else name


def blocked_reason(path):
    if "onedrive" in path.lower():
        return "OneDrive manages this folder, so move it from OneDrive's settings"
    return None


def current_path(name, api=None):
    return (api or WindowsFolders()).get(_folder_id(name))


def move(name, root, journal, api=None, progress=None, cancel=None, same_drive_ok=False):
    folders = api or WindowsFolders()
    folder_id = _folder_id(name)
    source = folders.get(folder_id)
    reason = blocked_reason(source)
    if reason:
        raise MoveError(reason)
    check = preflight.run(source, root, journal, None, same_drive_ok)
    if check.problems:
        raise MoveError("; ".join(check.problems))
    record = {
        "id": new_id(),
        "kind": "known",
        "known": name,
        "name": FOLDERS[name][0] if name in FOLDERS else name,
        "tool": None,
        "source": check.source,
        "target": check.target,
        "backup": check.source,
        "root": check.root,
        "bytes": check.size,
        "files": check.files,
        "created": int(time.time()),
        "pointer": False,
        "state": "copying",
    }
    journal.put(record)
    try:
        lock_destination(check.root, check.target)
        copy_and_verify(check.source, check.target, check.size, progress, cancel)
        record["state"] = "switching"
        journal.put(record)
        folders.set(folder_id, check.target)
    except BaseException as error:
        _discard(record, journal)
        if isinstance(error, OSError):
            raise MoveError(f"{record['name']}: {error}") from error
        raise
    record["state"] = "moved"
    journal.put(record)
    return record


def _discard(record, journal):
    remove_tree(record["target"])
    prune_empty(record["target"], normalize_root(record["root"]))
    journal.remove(record["id"])


def finish(record_id, journal, api=None):
    record = journal.get(record_id)
    if record["state"] == "finished":
        return record
    if not os.path.isdir(record["target"]):
        raise MoveError(f"{record['target']} is missing")
    if key((api or WindowsFolders()).get(_folder_id(record["known"]))) != key(record["target"]):
        raise MoveError(f"Windows no longer uses {record['target']} for {record['name']}, so the old copy stays")
    leftover = record["source"]
    for entry in os.listdir(long_path(leftover)) if os.path.isdir(long_path(leftover)) else []:
        remove_tree(os.path.join(leftover, entry))
    try:
        os.rmdir(long_path(leftover))
    except OSError:
        pass
    record["state"] = "finished"
    journal.put(record)
    return record


def undo(record_id, journal, api=None, progress=None, cancel=None):
    folders = api or WindowsFolders()
    record = journal.get(record_id)
    folder_id = _folder_id(record["known"])
    active = processes.running_from(record["target"])
    if active:
        names = sorted({os.path.basename(path) for path in active})
        raise MoveError(f"close {', '.join(names)} first")
    size = measure(record["target"])[0]
    if volumes.free_bytes(volumes.drive_of(record["source"])) < size:
        raise MoveError(f"not enough free space on {volumes.drive_of(record['source'])}")
    restore = record["source"] + RESTORE_SUFFIX
    remove_tree(restore)
    try:
        copy_and_verify(record["target"], restore, size, progress, cancel)
    except BaseException:
        remove_tree(restore)
        raise
    record["previous_state"] = record["state"]
    record["state"] = "restoring"
    journal.put(record)
    remove_tree(record["source"])
    os.rename(long_path(restore), long_path(record["source"]))
    folders.set(folder_id, record["source"])
    _discard(record, journal)
    return f"{record['name']} is back where it started."


def recover(journal, api=None):
    folders = api or WindowsFolders()
    messages = []
    for record in journal.records():
        if record.get("kind") != "known":
            continue
        folder_id = _folder_id(record["known"])
        if record["state"] == "copying":
            _discard(record, journal)
            messages.append(f"{record['name']}: the move was interrupted, so nothing changed")
        elif record["state"] == "switching":
            if key(folders.get(folder_id)) == key(record["target"]):
                record["state"] = "moved"
                journal.put(record)
                messages.append(f"{record['name']}: the move had finished")
            else:
                _discard(record, journal)
                messages.append(f"{record['name']}: the move was interrupted, so nothing changed")
        elif record["state"] == "restoring":
            restore = record["source"] + RESTORE_SUFFIX
            if os.path.isdir(restore):
                remove_tree(record["source"])
                os.rename(long_path(restore), long_path(record["source"]))
            folders.set(folder_id, record["source"])
            _discard(record, journal)
            messages.append(f"{record['name']}: finished the interrupted undo")
    return messages
