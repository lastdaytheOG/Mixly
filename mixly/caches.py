import os
from dataclasses import dataclass

from . import processes
from .copier import measure
from .links import is_junction, link_target, remove_tree
from .paths import long_path

NODE = ("node.exe",)
PYTHON = ("python.exe", "pythonw.exe", "pip.exe", "uv.exe")
JAVA = ("java.exe", "javaw.exe", "studio64.exe")


@dataclass(frozen=True)
class Cache:
    id: str
    name: str
    path: str
    processes: tuple = ()

    @property
    def source(self):
        return os.path.expandvars(self.path)


CACHES = (
    Cache("npm", "npm cache", r"%LOCALAPPDATA%\npm-cache", NODE),
    Cache("yarn", "Yarn cache", r"%LOCALAPPDATA%\Yarn\Cache", NODE),
    Cache("pip", "pip cache", r"%LOCALAPPDATA%\pip\Cache", PYTHON),
    Cache("uv", "uv cache", r"%LOCALAPPDATA%\uv\cache", PYTHON),
    Cache("go", "Go build cache", r"%LOCALAPPDATA%\go-build", ("go.exe", "gopls.exe")),
    Cache("nuget", "NuGet download cache", r"%LOCALAPPDATA%\NuGet\v3-cache", ("dotnet.exe", "devenv.exe")),
    Cache("gradle", "Gradle downloads", r"%USERPROFILE%\.gradle\caches", JAVA),
    Cache("electron", "Electron downloads", r"%LOCALAPPDATA%\electron\Cache", NODE),
    Cache("directx", "DirectX shader cache", r"%LOCALAPPDATA%\D3DSCache"),
    Cache("nvidia-dx", "NVIDIA DirectX shader cache", r"%LOCALAPPDATA%\NVIDIA\DXCache"),
    Cache("nvidia-gl", "NVIDIA OpenGL shader cache", r"%LOCALAPPDATA%\NVIDIA\GLCache"),
)


def real_path(cache):
    source = cache.source
    return link_target(source) if is_junction(source) else source


def size_of(cache):
    try:
        return measure(real_path(cache))[0]
    except OSError:
        return 0


def _has_contents(path):
    try:
        with os.scandir(long_path(path)) as entries:
            return next(entries, None) is not None
    except OSError:
        return False


def available(catalog=CACHES):
    return [cache for cache in catalog if _has_contents(real_path(cache))]


def clear(cache, names=None):
    active = processes.still_running(cache.processes, names)
    if active:
        raise OSError(f"close {', '.join(active)} before clearing {cache.name}")
    folder = real_path(cache)
    before = measure(folder)[0]
    skipped = 0
    with os.scandir(long_path(folder)) as entries:
        children = [entry.path for entry in entries]
    for child in children:
        try:
            remove_tree(child)
        except OSError:
            skipped += 1
    return before - measure(folder)[0], skipped
