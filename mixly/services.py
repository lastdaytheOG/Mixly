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
