import os

EXTENDED = "\\\\?\\"
EXTENDED_UNC = "\\\\?\\UNC\\"


def full(path):
    return os.path.abspath(os.path.expandvars(os.fspath(path)))


def key(path):
    return os.path.normcase(full(path)).rstrip("\\/")


def is_within(child, parent):
    child_key, parent_key = key(child), key(parent)
    return child_key == parent_key or child_key.startswith(parent_key + os.sep)


def long_path(path):
    value = os.path.abspath(os.fspath(path))
    if value.startswith(EXTENDED):
        return value
    if value.startswith("\\\\"):
        return EXTENDED_UNC + value[2:]
    return EXTENDED + value


def strip_extended(path):
    if path.startswith(EXTENDED_UNC):
        return "\\\\" + path[len(EXTENDED_UNC):]
    if path.startswith(EXTENDED):
        return path[len(EXTENDED):]
    return path


def normalize_root(root):
    value = os.fspath(root).strip()
    if len(value) == 2 and value[1] == ":":
        value += "\\"
    return full(value)


def target_for(root, source):
    drive, tail = os.path.splitdrive(full(source))
    if not drive.endswith(":"):
        raise ValueError(f"{source} is not on a local drive")
    return os.path.join(normalize_root(root), "Mixly", drive[0].upper(), tail.lstrip("\\/"))


def rebase(path, old_root, new_root):
    relative = full(path)[len(key(old_root)):].lstrip("\\/")
    return os.path.join(full(new_root), relative) if relative else full(new_root)


def _system_roots():
    drive = os.environ.get("SystemDrive", "C:") + "\\"
    names = ("windir", "ProgramFiles", "ProgramFiles(x86)", "ProgramW6432", "ProgramData")
    roots = [os.environ[name] for name in names if os.environ.get(name)]
    roots += [os.path.join(drive, name) for name in ("Recovery", "Boot", "$Recycle.Bin", "System Volume Information")]
    return roots


def _profile_roots():
    drive = os.environ.get("SystemDrive", "C:") + "\\"
    profile = os.environ.get("USERPROFILE", os.path.join(drive, "Users"))
    return [
        os.path.join(drive, "Users"),
        profile,
        os.path.join(profile, "AppData"),
        os.path.join(profile, "AppData", "LocalLow"),
        os.environ.get("APPDATA", os.path.join(profile, "AppData", "Roaming")),
        os.environ.get("LOCALAPPDATA", os.path.join(profile, "AppData", "Local")),
    ]


def protected_reason(path):
    value = full(path)
    if os.path.dirname(value) == value:
        return "a whole drive can't be moved"
    for root in _system_roots():
        if is_within(value, root):
            return f"{root} belongs to Windows"
    for root in _profile_roots():
        if is_within(root, value):
            return f"{value} holds {root}, which has to stay where it is"
    return None
