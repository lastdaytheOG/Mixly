import os
import sys
from dataclasses import dataclass, field

from . import elevation, processes, services, volumes
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
    found = services.in_folder(check.source)
    if found:
        check.problems.append(f"{check.source} stays put because it runs the Windows service {found[0].name}")
        return False
    return True


def _check_root(check, same_drive_ok):
    drive = volumes.drive_of(check.root)
    if not drive:
        check.problems.append(f"{check.root} isn't on a local drive")
        return
    if volumes.drive_type(drive) != volumes.DRIVE_FIXED:
        check.problems.append(f"{drive} isn't an internal drive")
    filesystem = volumes.volume_info(drive)[1]
    if filesystem != REQUIRED_FILESYSTEM:
        check.problems.append(f"{drive} is {filesystem or 'unreadable'}, and junctions need NTFS")
    if not same_drive_ok and drive == volumes.drive_of(check.source):
        check.problems.append(f"{check.source} is already on {drive}")


def _check_overlap(check, journal):
    if is_within(check.target, check.source) or is_within(check.root, check.source):
        check.problems.append("the destination is inside the folder being moved")
    for record in journal.records():
        for known in (record.get("source"), record.get("target")):
            if known and (is_within(check.source, known) or is_within(known, check.source)):
                check.problems.append(f"{check.source} overlaps {known}, which Mixly already moved")
                return


def _check_leftovers(check):
    if os.path.lexists(check.target):
        check.problems.append(f"{check.target} already exists")
    for suffix in (".mixly-old", ".mixly-restore"):
        if os.path.lexists(check.source + suffix):
            check.problems.append(f"{check.source + suffix} is still there from an earlier move")


def _check_in_use(check):
    active = processes.running_from(check.source)
    if active:
        names = sorted({os.path.basename(path) for path in active})
        check.problems.append(f"close {', '.join(names)} first")


def _check_access(check):
    if not elevation.can_replace(check.source):
        check.problems.append(f"{check.source} needs administrator rights")


def _check_contents(check, tool):
    try:
        check.size, check.files, unsupported, drivers = measure(check.source)
    except OSError as error:
        check.problems.append(f"couldn't read {check.source}: {error}")
        return
    if unsupported:
        check.problems.append(f"{unsupported[0]} can't be copied")
    if drivers and tool is not None and tool.id.startswith("app:"):
        check.problems.append(f"{check.source} stays put because it includes the driver {os.path.basename(drivers[0])}")
    try:
        free = volumes.free_bytes(volumes.drive_of(check.root))
    except OSError as error:
        check.problems.append(f"couldn't read free space: {error}")
        return
    needed = int(check.size * HEADROOM)
    if free < needed:
        check.problems.append(f"needs {volumes.format_size(needed)}, but only {volumes.format_size(free)} is free")


def run(source, root, journal, tool=None, same_drive_ok=False, names=None):
    check = Check(full(source))
    check.root = normalize_root(root)
    if not _check_source(check):
        return check
    _check_root(check, same_drive_ok)
    try:
        check.target = target_for(check.root, check.source)
    except ValueError as error:
        check.problems.append(str(error))
        return check
    _check_overlap(check, journal)
    _check_leftovers(check)
    if tool is not None and tool.processes:
        active = processes.still_running(tool.processes, names)
        if active:
            check.problems.append(f"close {', '.join(active)} first")
    _check_in_use(check)
    _check_access(check)
    _check_contents(check, tool)
    return check
