import os
from dataclasses import replace

from .catalog import Tool
from .links import is_junction

MINIMUM = 100 * 1024 * 1024
SKIPPED = {
    "microsoft",
    "packages",
    "temp",
    "programs",
    "package cache",
    "crashdumps",
    "d3dscache",
    "nvidia",
    "nvidia corporation",
    "comms",
    "connecteddevicesplatform",
    "placeholdertilelogofolder",
    "publishers",
    "virtualstore",
    "history",
    "low",
    "mixly",
}


def data_folders(parents=None):
    roots = parents if parents is not None else [os.environ.get("LOCALAPPDATA", ""), os.environ.get("APPDATA", "")]
    tools = []
    seen = {}
    for parent in roots:
        if not parent or not os.path.isdir(parent):
            continue
        tag = os.path.basename(parent.rstrip("\\/")) or "data"
        for name in sorted(os.listdir(parent)):
            path = os.path.join(parent, name)
            if name.lower() in SKIPPED or name.startswith(".") or not os.path.isdir(path):
                continue
            name_key = name.lower()
            if name_key in seen:
                first_idx, first_tag = seen[name_key]
                tools[first_idx] = replace(tools[first_idx], name=f"{name} ({first_tag}) data")
                tool_id = f"data:{name}:{tag.lower()}"
                tool_name = f"{name} ({tag}) data"
                tools.append(Tool(tool_id, tool_name, path))
            else:
                tool = Tool(f"data:{name}", f"{name} data", path)
                tools.append(tool)
                seen[name_key] = (len(tools) - 1, tag)
    return tools


def save_folders(profile=None):
    home = profile or os.environ.get("USERPROFILE", "")
    candidates = (
        ("saves:saved-games", "Saved Games", os.path.join(home, "Saved Games")),
        ("saves:my-games", "Documents\\My Games", os.path.join(home, "Documents", "My Games")),
    )
    return [Tool(tool_id, name, path) for tool_id, name, path in candidates if os.path.isdir(path) or is_junction(path)]
