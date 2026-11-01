import os
from dataclasses import dataclass

from . import appdata, caches, games, installed, services, volumes, wsl
from .catalog import CATALOG
from .copier import measure
from .links import is_junction, is_symlink
from .paths import is_within, protected_reason

DEVELOPER = "Developer tools"
GAMES = "Games"
APPS = "Apps"
DATA = "App data and saves"
PERSONAL = "Personal folders"
STORE = "Store apps"
CACHES = "Caches"
LARGE = "Large folders"
STAYS = "stays put"
CAN_CLEAR = "can clear"
PAUSED = "paused"
GUESSED_APP_MINIMUM = 1024 * 1024


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
    note: str = ""
    known: str = ""
    cache: object = None
    package: str = ""


def _system_drive():
    return os.environ.get("SystemDrive", "C:").upper()


def _folder(tool, states, category, listing):
    source = tool.source
    if not os.path.lexists(source):
        return None
    state = states.get(source.lower())
    if state and state != PAUSED:
        return Found(tool.id, tool.name, source, 0, "moved", tool, category=category)
    if is_junction(source) or is_symlink(source):
        return Found(tool.id, tool.name, source, 0, "linked elsewhere", tool, category=category)
    reason = protected_reason(source)
    note = ""
    found_services = services.in_folder(source, listing)
    blocking = [service for service in found_services if service.must_stay]
    if blocking:
        reason = f"Windows needs {blocking[0].name} early in startup"
    elif found_services:
        note = f"stops and restarts the service {found_services[0].name}"
    try:
        size, _, _, drivers = measure(source)
    except OSError:
        return Found(tool.id, tool.name, source, 0, "unreadable", tool, category=category)
    if drivers and tool.id.startswith("app:") and not reason:
        reason = f"it includes the driver {os.path.basename(drivers[0])}"
    if reason:
        return Found(tool.id, tool.name, source, size, STAYS, tool, category=category, reason=reason)
    if state == PAUSED:
        return Found(tool.id, tool.name, source, size, PAUSED, tool, category=category, note=note)
    drive = volumes.drive_of(source)
    if drive != _system_drive():
        return Found(tool.id, tool.name, source, size, f"already on {drive}", tool, category=category)
    return Found(tool.id, tool.name, source, size, "ready", tool, category=category, note=note)


def _service_listing():
    try:
        return services.list_services()
    except OSError:
        return []


def known_items(records):
    from . import known

    found = []
    for name, (label, _) in known.FOLDERS.items():
        record = next((item for item in records if item.get("known") == name), None)
        if record:
            found.append(Found(f"known:{name}", label, record["source"], 0, "moved", category=PERSONAL, known=name))
            continue
        try:
            path = known.current_path(name)
        except OSError:
            continue
        reason = known.blocked_reason(path)
        try:
            size = measure(path)[0]
        except OSError:
            size = 0
        if reason:
            found.append(Found(f"known:{name}", label, path, size, STAYS, category=PERSONAL, reason=reason, known=name))
        elif volumes.drive_of(path) != _system_drive():
            found.append(Found(f"known:{name}", label, path, size, f"already on {volumes.drive_of(path)}", category=PERSONAL, known=name))
        else:
            found.append(Found(f"known:{name}", label, path, size, "ready", category=PERSONAL, known=name, note="moves without a link"))
    return found


def store_items(records):
    from . import store_apps

    found = []
    for app in store_apps.list_apps():
        record = next((item for item in records if item.get("package") == app["package"]), None)
        if record:
            found.append(Found(f"store:{app['package']}", app["name"], record["source"], 0, "moved", category=STORE, package=app["package"]))
        elif volumes.drive_of(app["location"]) != _system_drive():
            found.append(Found(f"store:{app['package']}", app["name"], app["location"], 0, f"already on {volumes.drive_of(app['location'])}", category=STORE, package=app["package"]))
        else:
            found.append(Found(f"store:{app['package']}", app["name"], app["location"], 0, "ready", category=STORE, package=app["package"], note="Windows decides if it can move"))
    return found


def cache_items():
    return [
        Found(f"cache:{cache.id}", cache.name, cache.source, caches.size_of(cache), CAN_CLEAR, category=CACHES, cache=cache)
        for cache in caches.available()
    ]


def scan(journal, tools=CATALOG, include_wsl=True, on_found=None, include_installed=True, include_extras=None):
    extras = include_installed if include_extras is None else include_extras
    records = journal.records()
    states = {record["source"].lower(): record["state"] for record in records if record.get("kind") in ("folder", None)}
    listing = _service_listing()
    results = []
    seen = []

    def emit(found):
        results.append(found)
        if on_found is not None:
            on_found(found)

    def add(tool, category, minimum=0, skip_parents=False):
        if any(is_within(tool.source, known) for known in seen):
            return
        if skip_parents and any(is_within(known, tool.source) for known in seen):
            return
        found = _folder(tool, states, category, listing)
        if found is None or (found.status == "ready" and found.size < minimum):
            return
        seen.append(found.source)
        emit(found)

    for tool in tools:
        add(tool, DEVELOPER)
    if include_wsl:
        paths = wsl.base_paths()
        for distro in wsl.list_distros():
            name = distro["name"]
            if name.lower().startswith(wsl.RESERVED_PREFIX) or name not in paths:
                continue
            status = "moved" if any(record.get("distro") == name for record in records) else "ready"
            emit(Found(f"wsl:{name}", f"WSL: {name}", paths[name], wsl.disk_size(paths[name]), status, distro=name))
    if include_installed:
        for tool in games.all_games():
            add(tool, GAMES)
        for tool in installed.find_apps(discover=True):
            guessed = tool.id.startswith(("app:found:", "app:folder:"))
            add(tool, APPS, GUESSED_APP_MINIMUM if guessed else 0, skip_parents=True)
    if extras:
        for tool in appdata.save_folders():
            add(tool, DATA, skip_parents=True)
        for tool in appdata.data_folders():
            add(tool, DATA, appdata.MINIMUM, skip_parents=True)
        for found in known_items(records):
            emit(found)
        for found in store_items(records):
            emit(found)
        for found in cache_items():
            emit(found)
    return results
