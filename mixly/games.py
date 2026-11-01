import glob
import json
import os
import re
import winreg

from .catalog import Tool

PAIR = re.compile(r'"([^"\\]*(?:\\.[^"\\]*)*)"\s+"([^"\\]*(?:\\.[^"\\]*)*)"')
STEAM = ("steam.exe", "steamwebhelper.exe")
EPIC = ("EpicGamesLauncher.exe",)
GOG = ("GalaxyClient.exe",)
UBISOFT = ("upc.exe", "UbisoftConnect.exe")


def parse_pairs(text):
    return [(key, value.replace("\\\\", "\\")) for key, value in PAIR.findall(text)]


def _read(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            return handle.read()
    except OSError:
        return ""


def _registry_value(hive, key, name):
    try:
        with winreg.OpenKey(hive, key) as entry:
            return winreg.QueryValueEx(entry, name)[0]
    except OSError:
        return None


def _registry_children(hive, key):
    try:
        with winreg.OpenKey(hive, key) as root:
            names = []
            index = 0
            while True:
                try:
                    names.append(winreg.EnumKey(root, index))
                except OSError:
                    return names
                index += 1
    except OSError:
        return []


def steam_libraries(steam_root):
    libraries = [os.path.normpath(steam_root)]
    for key, value in parse_pairs(_read(os.path.join(steam_root, "steamapps", "libraryfolders.vdf"))):
        if key.lower() == "path":
            path = os.path.normpath(value)
            if path.lower() not in (library.lower() for library in libraries):
                libraries.append(path)
    return libraries


def steam_games(steam_root=None):
    root = steam_root or _registry_value(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath")
    if not root:
        return []
    games = []
    for library in steam_libraries(root):
        for manifest in glob.glob(os.path.join(glob.escape(library), "steamapps", "appmanifest_*.acf")):
            values = {key.lower(): value for key, value in parse_pairs(_read(manifest))}
            if not values.get("installdir"):
                continue
            path = os.path.join(library, "steamapps", "common", values["installdir"])
            if os.path.isdir(path):
                name = values.get("name", values["installdir"])
                games.append(Tool(f"steam:{values.get('appid', values['installdir'])}", name, path, (), STEAM))
    return games


def epic_games(manifests=None):
    folder = manifests or os.path.join(os.environ.get("ProgramData", r"C:\ProgramData"), "Epic", "EpicGamesLauncher", "Data", "Manifests")
    games = []
    for manifest in glob.glob(os.path.join(glob.escape(folder), "*.item")):
        try:
            values = json.loads(_read(manifest))
        except ValueError:
            continue
        path = values.get("InstallLocation")
        if not path or values.get("bIsIncompleteInstall") or not os.path.isdir(path):
            continue
        name = values.get("DisplayName") or os.path.basename(path)
        games.append(Tool(f"epic:{values.get('AppName', name)}", name, os.path.normpath(path), (), EPIC))
    return games


def gog_games():
    root = r"SOFTWARE\WOW6432Node\GOG.com\Games"
    games = []
    for child in _registry_children(winreg.HKEY_LOCAL_MACHINE, root):
        key = f"{root}\\{child}"
        path = _registry_value(winreg.HKEY_LOCAL_MACHINE, key, "path")
        if path and os.path.isdir(path):
            name = _registry_value(winreg.HKEY_LOCAL_MACHINE, key, "gameName") or os.path.basename(path)
            games.append(Tool(f"gog:{child}", name, os.path.normpath(path), (), GOG))
    return games
