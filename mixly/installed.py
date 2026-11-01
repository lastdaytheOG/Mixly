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
