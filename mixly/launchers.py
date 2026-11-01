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
