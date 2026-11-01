import os
import re
import subprocess
import time
import winreg
from dataclasses import dataclass

from .paths import is_within

SERVICES = r"SYSTEM\CurrentControlSet\Services"
DRIVER_TYPES = 0x1 | 0x2 | 0x8
EARLY_STARTS = (0, 1)
USER_SERVICE = 0x10
DEMAND_START = 3
STOPPED = 1
RUNNING = 4
STATE = re.compile(r"STATE\s*:\s*(\d+)")
CREATE_NO_WINDOW = 0x08000000


class ServiceError(Exception):
    pass


@dataclass(frozen=True)
class Service:
    name: str
    path: str
    kind: int = USER_SERVICE
    start: int = DEMAND_START

    @property
    def must_stay(self):
        return bool(self.kind & DRIVER_TYPES) or self.start in EARLY_STARTS


def image_path(raw):
    value = raw.strip()
    if value.startswith("\\??\\"):
        value = value[4:]
    if value.startswith('"'):
        end = value.find('"', 1)
        return value[1:end] if end > 0 else value[1:]
    lowered = value.lower()
    for extension in (".exe", ".sys"):
        index = lowered.find(extension)
        if index >= 0:
            return value[: index + len(extension)]
    return value


def _number(entry, name, default):
    try:
        return int(winreg.QueryValueEx(entry, name)[0])
    except (OSError, ValueError, TypeError):
        return default


def list_services():
    services = []
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, SERVICES) as root:
        index = 0
        while True:
            try:
                name = winreg.EnumKey(root, index)
            except OSError:
                return services
            index += 1
            try:
                with winreg.OpenKey(root, name) as entry:
                    raw = winreg.QueryValueEx(entry, "ImagePath")[0]
                    kind = _number(entry, "Type", USER_SERVICE)
                    start = _number(entry, "Start", DEMAND_START)
            except OSError:
                continue
            path = os.path.expandvars(image_path(str(raw)))
            if os.path.isabs(path) and path[1:2] == ":":
                services.append(Service(name, path, kind, start))


def in_folder(folder, listing=None):
    available = list_services() if listing is None else listing
    return [service for service in available if is_within(service.path, folder)]
