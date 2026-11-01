import os
import winreg
from dataclasses import dataclass

from .paths import is_within

SERVICES = r"SYSTEM\CurrentControlSet\Services"


@dataclass(frozen=True)
class Service:
    name: str
    path: str


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
            except OSError:
                continue
            path = os.path.expandvars(image_path(str(raw)))
            if os.path.isabs(path) and path[1:2] == ":":
                services.append(Service(name, path))


def in_folder(folder, listing=None):
    available = list_services() if listing is None else listing
    return [service for service in available if is_within(service.path, folder)]
