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
