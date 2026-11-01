import os
from dataclasses import dataclass

from . import games, installed, services, volumes, wsl
from .catalog import CATALOG
from .copier import measure
from .links import is_junction, is_symlink
from .paths import is_within, protected_reason

DEVELOPER = "Developer tools"
GAMES = "Games"
APPS = "Apps"
STAYS = "stays put"


@dataclass
class Found:
    id: str
    name: str
    source: str
    size: int
    status: str
    tool: object = None
    distro: str = ""
    category: str = DEVELOPER
    reason: str = ""


def _folder(tool, moved, category, listing):
    source = tool.source
    if not os.path.lexists(source):
        return None
    if source.lower() in moved:
        return Found(tool.id, tool.name, source, 0, "moved", tool, category=category)
    if is_junction(source) or is_symlink(source):
        return Found(tool.id, tool.name, source, 0, "linked elsewhere", tool, category=category)
    reason = protected_reason(source)
    found_services = services.in_folder(source, listing)
    if found_services:
        reason = f"it runs the Windows service {found_services[0].name}"
    try:
        size, _, _, drivers = measure(source)
    except OSError:
        return Found(tool.id, tool.name, source, 0, "unreadable", tool, category=category)
    if drivers and tool.id.startswith("app:") and not reason:
        reason = f"it includes the driver {os.path.basename(drivers[0])}"
    if reason:
        return Found(tool.id, tool.name, source, size, STAYS, tool, category=category, reason=reason)
    drive = volumes.drive_of(source)
    if drive != os.environ.get("SystemDrive", "C:").upper():
        return Found(tool.id, tool.name, source, size, f"already on {drive}", tool, category=category)
    return Found(tool.id, tool.name, source, size, "ready", tool, category=category)


def _service_listing():
    try:
        return services.list_services()
    except OSError:
        return []


def scan(journal, tools=CATALOG, include_wsl=True, on_found=None, include_installed=True):
    moved = {record["source"].lower() for record in journal.records()}
    listing = _service_listing()
    results = []
    seen = []

    def add(tool, category):
        if any(is_within(tool.source, known) for known in seen):
            return
        found = _folder(tool, moved, category, listing)
        if found is None:
            return
        seen.append(found.source)
        results.append(found)
        if on_found is not None:
            on_found(found)

    for tool in tools:
        add(tool, DEVELOPER)
    if include_wsl:
        paths = wsl.base_paths()
        for distro in wsl.list_distros():
            name = distro["name"]
            if name.lower().startswith(wsl.RESERVED_PREFIX) or name not in paths:
                continue
            status = "moved" if paths[name].lower() in moved or any(
                record.get("distro") == name for record in journal.records()
            ) else "ready"
            found = Found(f"wsl:{name}", f"WSL: {name}", paths[name], wsl.disk_size(paths[name]), status, distro=name)
            results.append(found)
            if on_found is not None:
                on_found(found)
    if include_installed:
        for tool in games.all_games():
            add(tool, GAMES)
        for tool in installed.find_apps():
            add(tool, APPS)
    return results
