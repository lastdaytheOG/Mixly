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


def _state_of(name, run):
    for distro in list_distros(run):
        if distro["name"] == name:
            return distro
    raise WslError(f"{name} isn't installed")


def _require_all_stopped(run):
    active = [distro["name"] for distro in list_distros(run) if distro["state"].lower() != "stopped"]
    if active:
        names = ", ".join(active)
        raise WslError(f"{names} still running. Save your work, then run: wsl --shutdown")


def _run_move(name, destination, run):
    _require_all_stopped(run)
    run(["--shutdown"])
    os.makedirs(destination, exist_ok=True)
    result = run(["--manage", name, "--move", destination])
    if result.returncode != 0:
        message = _decode(result.stdout + result.stderr).strip()
        raise WslError(f"wsl couldn't move {name}: {message or result.returncode}")


def move(name, root, journal, run=_run, paths=base_paths):
    if name.lower().startswith(RESERVED_PREFIX):
        raise WslError(f"{name} belongs to Docker Desktop, so move it with the Docker Desktop entry")
    _state_of(name, run)
    _require_all_stopped(run)
    source = paths().get(name)
    if not source:
        raise WslError(f"couldn't find where {name} is stored")
    normalized = normalize_root(root)
    drive = volumes.drive_of(normalized)
    if drive == volumes.drive_of(source):
        raise WslError(f"{name} is already on {drive}")
    size = disk_size(source)
    if volumes.free_bytes(drive) < int(size * 1.05):
        raise WslError(f"not enough free space on {drive} for {name}")
    destination = os.path.join(normalized, "Mixly", "WSL", name)
    _run_move(name, destination, run)
    if key(paths().get(name, "")) != key(destination):
        raise WslError(f"wsl reported success, but {name} didn't move to {destination}")
    record = {
        "id": new_id(),
        "kind": "wsl",
        "name": f"WSL: {name}",
        "distro": name,
        "tool": None,
        "source": source,
        "target": destination,
        "root": normalized,
        "bytes": size,
        "files": 1,
        "created": int(time.time()),
        "pointer": False,
        "state": "moved",
    }
    journal.put(record)
    return record
