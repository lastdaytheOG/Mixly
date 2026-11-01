import os

EXTENDED = "\\\\?\\"
EXTENDED_UNC = "\\\\?\\UNC\\"
STORE_FOLDERS = ("windowsapps", "modifiablewindowsapps")
SHARED_FOLDERS = (
    "common files",
    "internet explorer",
    "dotnet",
    "packagemanagement",
    "reference assemblies",
    "msbuild",
    "uninstall information",
    "installshield installation information",
)
HARDWARE_FOLDERS = (
    "nvidia corporation",
    "nvidia",
    "intel",
    "amd",
    "ati technologies",
    "realtek",
    "lenovo",
    "dell",
    "hp",
    "hewlett-packard",
    "asus",
    "acer",
    "msi",
    "razer",
    "logitech",
)


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
    roots = [os.environ[name] for name in ("windir", "ProgramData") if os.environ.get(name)]
    roots += [os.path.join(drive, name) for name in ("Recovery", "Boot", "$Recycle.Bin", "System Volume Information")]
    for name in ("LOCALAPPDATA", "APPDATA"):
        if os.environ.get(name):
            roots.append(os.path.join(os.environ[name], "Microsoft"))
    if os.environ.get("LOCALAPPDATA"):
        roots.append(os.path.join(os.environ["LOCALAPPDATA"], "Package Cache"))
    return roots


def _program_files_reason(value):
    names = ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432")
    for root in (os.environ[name] for name in names if os.environ.get(name)):
        if not is_within(value, root) and not is_within(root, value):
            continue
        if is_within(root, value):
            return f"{value} holds {root}, which has to stay where it is"
        first = full(value)[len(key(root)):].lstrip("\\/").split(os.sep)[0].lower()
        if first in STORE_FOLDERS:
            return "Store and Xbox apps can only be moved from Windows Settings"
        if first.startswith(("windows", "microsoft")) or first in SHARED_FOLDERS:
            return f"{first} belongs to Windows"
        if first in HARDWARE_FOLDERS:
            return f"{first} is hardware support software"
    return None


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
    if is_within(value, os.path.join(os.environ.get("SystemDrive", "C:") + "\\", "XboxGames")):
        return "Store and Xbox apps can only be moved from Windows Settings"
    reason = _program_files_reason(value)
    if reason:
        return reason
    for root in _profile_roots():
        if is_within(root, value):
            return f"{value} holds {root}, which has to stay where it is"
    return None
