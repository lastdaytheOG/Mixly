import json
import os
import re
import subprocess
import time

from . import volumes
from .journal import new_id
from .mover import MoveError

CREATE_NO_WINDOW = 0x08000000
SAFE_PACKAGE = re.compile(r"^[A-Za-z0-9._~-]+$")
HIDDEN_WORDS = (
    "nvidia",
    "intel",
    "appup.",
    "lenovo",
    "e046963",
    "e0469640",
    "nahimic",
    "a-volute",
    "realtek",
    "dolby",
    "extension",
    "runtime",
    "winget",
    "xbox",
    "gamingservices",
    "desktopappinstaller",
    "windowsstore",
    "storepurchase",
    "sechealth",
    "speech",
    "webexperience",
    "crossdevice",
    "applicationcompatibility",
)
LIST_SCRIPT = (
    "[Console]::OutputEncoding=[Text.Encoding]::UTF8;"
    "Get-AppxPackage | Where-Object { -not $_.IsFramework -and -not $_.IsResourcePackage -and -not $_.IsBundle "
    "-and -not $_.NonRemovable -and $_.SignatureKind -eq 'Store' } | "
    "ForEach-Object { [pscustomobject]@{name=$_.Name;package=$_.PackageFullName;location=$_.InstallLocation} } | "
    "ConvertTo-Json -Compress"
)


def _powershell(script):
    return subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=CREATE_NO_WINDOW,
    )


def parse_list(text):
    clean = (text or "").strip()
    if not clean:
        return []
    data = json.loads(clean)
    return [data] if isinstance(data, dict) else data


def _is_part_of_windows(name):
    lowered = name.lower()
    return any(word in lowered for word in HIDDEN_WORDS)


def list_apps(run=_powershell):
    result = run(LIST_SCRIPT)
    if result.returncode != 0:
        return []
    return [app for app in parse_list(result.stdout) if app.get("location") and not _is_part_of_windows(app.get("name", ""))]


def _volume(root):
    drive = volumes.drive_of(root)
    if not re.fullmatch(r"[A-Z]:", drive):
        raise MoveError(f"{root} isn't on a local drive")
    return f"{drive}\\"


def move_script(package, volume):
    if not SAFE_PACKAGE.fullmatch(package):
        raise MoveError(f"{package} isn't a valid package name")
    return (
        "$ErrorActionPreference='Stop';"
        f"if (-not (Get-AppxVolume | Where-Object {{ $_.PackageStorePath -like '{volume}*' }})) {{ Add-AppxVolume -Path '{volume}' }};"
        f"Move-AppxPackage -Package '{package}' -Volume '{volume}'"
    )


def _location_of(package, run):
    for app in list_apps(run):
        if app["package"] == package:
            return app["location"]
    return ""


def _run_move(name, package, volume, run):
    result = run(move_script(package, volume))
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "").strip().splitlines()
        raise MoveError(f"Windows wouldn't move {name}: {message[0] if message else result.returncode}")
    location = _location_of(package, run)
    if volumes.drive_of(location) != volume[:2]:
        raise MoveError(f"Windows reported success, but {name} is still at {location or 'an unknown location'}")
    return location


def move(package, name, root, journal, run=_powershell):
    source = _location_of(package, run)
    volume = _volume(root)
    if volumes.drive_of(source) == volume[:2]:
        raise MoveError(f"{name} is already on {volume[:2]}")
    target = _run_move(name, package, volume, run)
    record = {
        "id": new_id(),
        "kind": "store",
        "name": name,
        "package": package,
        "tool": None,
        "source": source,
        "target": target,
        "root": volume,
        "bytes": 0,
        "files": 0,
        "created": int(time.time()),
        "pointer": False,
        "state": "moved",
    }
    journal.put(record)
    return record
