import json
import os
import re
import subprocess
import winreg

from .catalog import Tool
from .paths import is_within, protected_reason

CREATE_NO_WINDOW = 0x08000000
SUBFOLDERS = ("bin", "64bit", "32bit", "x64", "x86", "application")
VERSION = re.compile(r"v?\d+(\.\d+)+")
UNINSTALL = r"Software\Microsoft\Windows\CurrentVersion\Uninstall"
SOURCES = (
    (winreg.HKEY_LOCAL_MACHINE, UNINSTALL),
    (winreg.HKEY_LOCAL_MACHINE, r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
    (winreg.HKEY_CURRENT_USER, UNINSTALL),
)
APP_PATHS = (
    (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\App Paths"),
    (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\App Paths"),
)
NOT_THE_APP = ("unins", "setup", "install", "update", "helper", "crash", "report")
SHORTCUT_SCRIPT = (
    "[Console]::OutputEncoding=[Text.Encoding]::UTF8;"
    "$shell=New-Object -ComObject WScript.Shell;"
    "$folders=@([Environment]::GetFolderPath('Programs'),[Environment]::GetFolderPath('CommonPrograms'));"
    "Get-ChildItem $folders -Recurse -Filter *.lnk -ErrorAction SilentlyContinue | "
    "ForEach-Object { [pscustomobject]@{name=$_.BaseName;target=$shell.CreateShortcut($_.FullName).TargetPath} } | "
    "ConvertTo-Json -Compress"
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


def _skip_program(path):
    name = os.path.basename(path).lower()
    return not name.endswith(".exe") or any(word in name for word in NOT_THE_APP)


def shortcuts(run=None):
    result = (run or _powershell)(SHORTCUT_SCRIPT)
    if result.returncode != 0 or not (result.stdout or "").strip():
        return []
    try:
        data = json.loads(result.stdout)
    except ValueError:
        return []
    return [data] if isinstance(data, dict) else data


def _powershell(script):
    return subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=CREATE_NO_WINDOW,
    )


def app_paths(sources=APP_PATHS):
    found = []
    for name, values in _entries(sources):
        target = str(values.get("") or "").strip().strip('"')
        if target:
            found.append({"name": os.path.splitext(name)[0], "target": target})
    return found


def program_files_folders(roots=None):
    names = ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432")
    parents = roots if roots is not None else list({os.environ[name] for name in names if os.environ.get(name)})
    found = []
    for parent in parents:
        if not os.path.isdir(parent):
            continue
        for name in sorted(os.listdir(parent)):
            path = os.path.join(parent, name)
            if os.path.isdir(path) and not protected_reason(path):
                found.append((name, path))
    return found


def _add_discovered(candidates, targets, folders):
    known = list(candidates.values())

    def overlaps(path):
        return any(is_within(path, tool.path) or is_within(tool.path, path) for tool in known)

    for entry in targets:
        target = str(entry.get("target") or "")
        if not os.path.isabs(target) or _skip_program(target):
            continue
        folder = app_root(os.path.dirname(target))
        if not os.path.isdir(folder) or protected_reason(folder) or overlaps(folder):
            continue
        tool = Tool(f"app:found:{folder.lower()}", str(entry.get("name") or os.path.basename(folder)), folder)
        candidates[folder.lower()] = tool
        known.append(tool)
    for name, folder in folders:
        if overlaps(folder):
            continue
        tool = Tool(f"app:folder:{folder.lower()}", name, folder)
        candidates[folder.lower()] = tool
        known.append(tool)


def find_apps(sources=SOURCES, discover=False):
    candidates = {}
    for name, values in _entries(sources):
        if values.get("SystemComponent") == 1 or values.get("ParentKeyName") or not values.get("DisplayName"):
            continue
        location = location_of(values)
        if not location or not os.path.isdir(location) or protected_reason(location):
            continue
        candidates.setdefault(location.lower(), Tool(f"app:{name}", str(values["DisplayName"]), location))
    if discover:
        _add_discovered(candidates, shortcuts() + app_paths(), program_files_folders())
    apps = []
    for tool in sorted(candidates.values(), key=lambda item: len(item.path)):
        if not any(is_within(tool.path, app.path) for app in apps):
            apps.append(tool)
    return sorted(apps, key=lambda item: item.name.lower())
