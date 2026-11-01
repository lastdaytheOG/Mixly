import ctypes
import os
import shutil
import string
from dataclasses import dataclass

DRIVE_FIXED = 3


@dataclass(frozen=True)
class Drive:
    letter: str
    label: str
    filesystem: str
    free: int
    total: int

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
