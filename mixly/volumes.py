import ctypes
import os
import shutil
import string
from dataclasses import dataclass

DRIVE_FIXED = 3
DRIVE_REMOVABLE = 2


@dataclass(frozen=True)
class Drive:
    letter: str
    label: str
    filesystem: str
    free: int
    total: int
    removable: bool = False

    @property
    def root(self):
        return f"{self.letter}:\\"


def drive_of(path):
    return os.path.splitdrive(os.path.abspath(path))[0].upper()


def drive_type(drive):
    return ctypes.windll.kernel32.GetDriveTypeW(f"{drive.rstrip(chr(92))}\\")


def volume_info(drive):
    label = ctypes.create_unicode_buffer(261)
    filesystem = ctypes.create_unicode_buffer(261)
    found = ctypes.windll.kernel32.GetVolumeInformationW(
        f"{drive.rstrip(chr(92))}\\", label, 261, None, None, None, filesystem, 261
    )
    return (label.value, filesystem.value) if found else ("", "")


def free_bytes(drive):
    return shutil.disk_usage(f"{drive.rstrip(chr(92))}\\").free


def list_drives(include_removable=False):
    mask = ctypes.windll.kernel32.GetLogicalDrives()
    allowed = (DRIVE_FIXED, DRIVE_REMOVABLE) if include_removable else (DRIVE_FIXED,)
    drives = []
    for index, letter in enumerate(string.ascii_uppercase):
        if not mask >> index & 1:
            continue
        kind = drive_type(f"{letter}:")
        if kind not in allowed:
            continue
        label, filesystem = volume_info(f"{letter}:")
        try:
            usage = shutil.disk_usage(f"{letter}:\\")
        except OSError:
            continue
        drives.append(Drive(letter, label, filesystem, usage.free, usage.total, kind == DRIVE_REMOVABLE))
    return drives


def format_size(size):
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024:
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"
