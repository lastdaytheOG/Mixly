import os
import sys
from dataclasses import dataclass, field

from . import processes, volumes
from .copier import measure
from .links import is_junction, is_symlink
from .paths import full, is_within, normalize_root, protected_reason, target_for

HEADROOM = 1.05
REQUIRED_FILESYSTEM = "NTFS"


@dataclass
class Check:
    source: str
    target: str = ""
    root: str = ""
    size: int = 0
    files: int = 0
    problems: list = field(default_factory=list)


def _own_paths():
    return [sys.executable, os.path.abspath(__file__), os.getcwd()]


def _check_source(check):
    if not os.path.lexists(check.source):
        check.problems.append(f"{check.source} doesn't exist")
        return False
    if is_junction(check.source) or is_symlink(check.source):
        check.problems.append(f"{check.source} is already a link")
        return False
    if not os.path.isdir(check.source):
        check.problems.append(f"{check.source} isn't a folder")
        return False
    reason = protected_reason(check.source)
    if reason:
        check.problems.append(reason)
        return False
    for path in _own_paths():
        if is_within(path, check.source):
            check.problems.append(f"{check.source} is in use by Mixly itself ({path})")
            return False
    return True
