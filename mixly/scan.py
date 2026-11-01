import os
from dataclasses import dataclass

from . import wsl
from .catalog import CATALOG
from .copier import measure
from .links import is_junction, is_symlink


@dataclass
class Found:
    id: str
    name: str
    source: str
    size: int
    status: str
    tool: object = None
    distro: str = ""


def _folder(tool, moved):
    source = tool.source
    if not os.path.lexists(source):
        return None
    if source.lower() in moved:
        return Found(tool.id, tool.name, source, 0, "moved", tool)
    if is_junction(source) or is_symlink(source):
        return Found(tool.id, tool.name, source, 0, "linked elsewhere", tool)
    try:
        size = measure(source)[0]
    except OSError:
        return Found(tool.id, tool.name, source, 0, "unreadable", tool)
    return Found(tool.id, tool.name, source, size, "ready", tool)


def scan(journal, tools=CATALOG, include_wsl=True, on_found=None):
    moved = {record["source"].lower() for record in journal.records()}
    results = []
    for tool in tools:
        found = _folder(tool, moved)
        if found is None:
            continue
        results.append(found)
        if on_found is not None:
            on_found(found)
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
    return results
