import os
import re
import winreg

from .catalog import Tool
from .paths import is_within, protected_reason

SUBFOLDERS = ("bin", "64bit", "32bit", "x64", "x86", "application")
VERSION = re.compile(r"v?\d+(\.\d+)+")
UNINSTALL = r"Software\Microsoft\Windows\CurrentVersion\Uninstall"
SOURCES = (
    (winreg.HKEY_LOCAL_MACHINE, UNINSTALL),
    (winreg.HKEY_LOCAL_MACHINE, r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
    (winreg.HKEY_CURRENT_USER, UNINSTALL),
)


def _values(key):
    values = {}
    index = 0
    while True:
        try:
            name, value, _ = winreg.EnumValue(key, index)
        except OSError:
            return values
        values[name] = value
        index += 1


def icon_folder(icon):
    value = str(icon).strip().strip('"')
    path = value.rsplit(",", 1)[0].strip().strip('"')
    if path.lower().endswith(".exe") and os.path.isabs(path):
        return os.path.dirname(path)
    return ""


def app_root(folder):
    current = os.path.normpath(folder)
    while True:
        name = os.path.basename(current).lower()
        parent = os.path.dirname(current)
        if parent == current or protected_reason(parent) or not (name in SUBFOLDERS or VERSION.fullmatch(name)):
            return current
        current = parent


def location_of(values):
    location = str(values.get("InstallLocation") or "").strip().strip('"')
    if not location:
        location = icon_folder(values.get("DisplayIcon") or "")
    return app_root(location) if location else ""


def _entries(sources):
    for hive, path in sources:
        try:
            root = winreg.OpenKey(hive, path)
        except OSError:
            continue
        with root:
            index = 0
            while True:
                try:
                    name = winreg.EnumKey(root, index)
                except OSError:
                    break
                index += 1
                try:
                    with winreg.OpenKey(root, name) as entry:
                        yield name, _values(entry)
                except OSError:
                    continue


def find_apps(sources=SOURCES):
    candidates = {}
    for name, values in _entries(sources):
        if values.get("SystemComponent") == 1 or values.get("ParentKeyName") or not values.get("DisplayName"):
            continue
        location = location_of(values)
        if not location or not os.path.isdir(location) or protected_reason(location):
            continue
        candidates.setdefault(location.lower(), Tool(f"app:{name}", str(values["DisplayName"]), location))
    apps = []
    for tool in sorted(candidates.values(), key=lambda item: len(item.path)):
        if not any(is_within(tool.path, app.path) for app in apps):
            apps.append(tool)
    return sorted(apps, key=lambda item: item.name.lower())
