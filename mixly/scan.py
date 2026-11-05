import os
from concurrent.futures import ThreadPoolExecutor
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
FILES = "Files"
MOVED = "Moved"
STAYS = "stays put"
CAN_CLEAR = "can clear"
PAUSED = "paused"
GUESSED_APP_MINIMUM = 1024 * 1024
WORKERS = 8


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
    pending: bool = False
    minimum: int = 0
    hidden: bool = False
    is_item: bool = False
    is_folder: bool = True
    record_id: str = ""


def _service_listing():
    try:
        return services.list_services()
    except OSError:
        return []


def _cached(sizes, path):
    return sizes.get(path) if sizes is not None else None


def identify(tool, states, category, listing, minimum=0, sizes=None):
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
    cached = _cached(sizes, source)
    size = cached[0] if cached else 0
    driver = cached[1] if cached else ""
    if driver and tool.id.startswith("app:") and not reason:
        reason = f"it includes the driver {driver}"
    status = STAYS if reason else (PAUSED if state == PAUSED else "ready")
    return Found(tool.id, tool.name, source, size, status, tool, category=category, reason=reason, note=note, pending=True, minimum=minimum)


def settle(found, sizes=None):
    if not found.pending:
        return found
    try:
        size, _, _, drivers = measure(found.source)
    except OSError:
        found.pending = False
        found.status = "unreadable"
        return found
    found.size = size
    found.pending = False
    driver = os.path.basename(drivers[0]) if drivers else ""
    if sizes is not None:
        sizes.put(found.source, size, driver)
    tool_id = found.tool.id if found.tool is not None else ""
    if driver and tool_id.startswith("app:") and not found.reason:
        found.reason = f"it includes the driver {driver}"
        found.status = STAYS
    if found.status in ("ready", CAN_CLEAR) and size < found.minimum:
        found.hidden = True
    return found


def known_items(records, sizes=None):
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
        cached = _cached(sizes, path)
        status = STAYS if reason else "ready"
        note = "" if reason else "moves without a link"
        found.append(Found(f"known:{name}", label, path, cached[0] if cached else 0, status, category=PERSONAL, reason=reason or "", known=name, note=note, pending=True))
    return found


def store_items(records):
    from . import store_apps

    found = []
    for app in store_apps.list_apps():
        record = next((item for item in records if item.get("package") == app["package"]), None)
        if record:
            found.append(Found(f"store:{app['package']}", app["name"], record["source"], 0, "moved", category=STORE, package=app["package"]))
        else:
            found.append(Found(f"store:{app['package']}", app["name"], app["location"], 0, "ready", category=STORE, package=app["package"], note="Windows decides if it can move"))
    return found


def cache_items(sizes=None):
    found = []
    for cache in caches.available():
        cached = _cached(sizes, cache.source)
        found.append(Found(f"cache:{cache.id}", cache.name, cache.source, cached[0] if cached else 0, CAN_CLEAR, category=CACHES, cache=cache, pending=True, minimum=1))
    return found


def discover(journal, tools=CATALOG, include_wsl=True, on_found=None, include_installed=True, include_extras=None, sizes=None):
    extras = include_installed if include_extras is None else include_extras
    records = journal.records()
    states = {record["source"].lower(): record["state"] for record in records if record.get("kind") in ("folder", None)}
    listing = _service_listing()
    results = []
    seen = []
    seen_ids = set()

    def emit(found):
        if found.id in seen_ids:
            return
        seen_ids.add(found.id)
        results.append(found)
        if on_found is not None:
            on_found(found)
    def add(tool, category, minimum=0, skip_parents=False):
        if any(is_within(tool.source, known) for known in seen):
            return
        if skip_parents and any(is_within(known, tool.source) for known in seen):
            return
        found = identify(tool, states, category, listing, minimum, sizes)
        if found is None:
            return
        seen.append(found.source)
        emit(found)

    for tool in tools:
        add(tool, DEVELOPER)
    if extras:
        for found in known_items(records, sizes):
            emit(found)
        for found in cache_items(sizes):
            emit(found)
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
        for found in store_items(records):
            emit(found)
    return results


def scan(journal, tools=CATALOG, include_wsl=True, on_found=None, include_installed=True, include_extras=None, sizes=None):
    items = discover(journal, tools, include_wsl, None, include_installed, include_extras, sizes)
    with ThreadPoolExecutor(WORKERS) as pool:
        list(pool.map(lambda item: settle(item, sizes), items))
    results = [item for item in items if not item.hidden]
    if on_found is not None:
        for item in results:
            on_found(item)
    return results
