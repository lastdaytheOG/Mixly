import os
import subprocess
import time
import winreg

from . import volumes
from .journal import new_id
from .paths import key, normalize_root, strip_extended

LXSS = r"Software\Microsoft\Windows\CurrentVersion\Lxss"
CREATE_NO_WINDOW = 0x08000000
RESERVED_PREFIX = "docker-desktop"
DISK_NAME = "ext4.vhdx"


class WslError(Exception):
    pass


def _run(arguments):
    environment = dict(os.environ, WSL_UTF8="1")
    return subprocess.run(
        ["wsl.exe", *arguments], capture_output=True, env=environment, creationflags=CREATE_NO_WINDOW
    )


def _decode(raw):
    if b"\x00" in raw:
        return raw.decode("utf-16-le", errors="replace")
    return raw.decode("utf-8", errors="replace")


def parse_list(text):
    distros = []
    for line in text.splitlines()[1:]:
        parts = line.replace("*", " ").split()
        if len(parts) >= 3:
            distros.append({"name": parts[0], "state": parts[1], "version": parts[2]})
    return distros


def list_distros(run=_run):
    try:
        result = run(["--list", "--verbose"])
    except FileNotFoundError:
        return []
    if result.returncode != 0:
        return []
    return parse_list(_decode(result.stdout))


def base_paths():
    paths = {}
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, LXSS) as root:
            index = 0
            while True:
                try:
                    name = winreg.EnumKey(root, index)
                except OSError:
                    return paths
                index += 1
                with winreg.OpenKey(root, name) as entry:
                    try:
                        distro = winreg.QueryValueEx(entry, "DistributionName")[0]
                        base = winreg.QueryValueEx(entry, "BasePath")[0]
                    except FileNotFoundError:
                        continue
                    paths[distro] = strip_extended(base)
    except FileNotFoundError:
        return paths


def disk_size(base):
    try:
        return os.path.getsize(os.path.join(base, DISK_NAME))
    except OSError:
        return 0
