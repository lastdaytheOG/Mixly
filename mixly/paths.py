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
