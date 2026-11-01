import os
from dataclasses import dataclass

NODE = ("node.exe",)
PYTHON = ("python.exe", "pythonw.exe", "pip.exe")
JAVA = ("java.exe", "javaw.exe", "studio64.exe")
RUST = ("cargo.exe", "rustc.exe", "rust-analyzer.exe")
GO = ("go.exe", "gopls.exe")
DOCKER = ("Docker Desktop.exe", "com.docker.backend.exe", "wslhost.exe", "wslrelay.exe")


@dataclass(frozen=True)
class Tool:
    id: str
    name: str
    path: str
    env: tuple = ()
    processes: tuple = ()
    native: bool = False

    @property
    def source(self):
        return os.path.expandvars(self.path)


CATALOG = (
    Tool("npm-cache", "npm cache", r"%LOCALAPPDATA%\npm-cache", ("npm_config_cache",), NODE, True),
    Tool("npm-global", "npm global packages", r"%APPDATA%\npm", (), NODE),
    Tool("pnpm", "pnpm", r"%LOCALAPPDATA%\pnpm", (), NODE),
    Tool("yarn", "Yarn", r"%LOCALAPPDATA%\Yarn", (), NODE),
    Tool("bun", "Bun", r"%USERPROFILE%\.bun", ("BUN_INSTALL",), ("bun.exe",)),
    Tool("nvm", "nvm for Windows", r"%APPDATA%\nvm", (), NODE),
    Tool("pip-cache", "pip cache", r"%LOCALAPPDATA%\pip\Cache", ("PIP_CACHE_DIR",), PYTHON, True),
    Tool("uv", "uv", r"%LOCALAPPDATA%\uv", (), ("uv.exe",) + PYTHON),
    Tool("python", "Python", r"%LOCALAPPDATA%\Programs\Python", (), PYTHON),
    Tool("conda", "conda environments", r"%USERPROFILE%\.conda", (), ("conda.exe",) + PYTHON),
    Tool("miniconda", "Miniconda", r"%USERPROFILE%\miniconda3", (), ("conda.exe",) + PYTHON),
    Tool("anaconda", "Anaconda", r"%USERPROFILE%\anaconda3", (), ("conda.exe",) + PYTHON),
    Tool("cargo", "Cargo", r"%USERPROFILE%\.cargo", ("CARGO_HOME",), RUST, True),
    Tool("rustup", "rustup toolchains", r"%USERPROFILE%\.rustup", ("RUSTUP_HOME",), RUST, True),
    Tool("go", "Go packages", r"%USERPROFILE%\go", ("GOPATH",), GO, True),
    Tool("go-cache", "Go build cache", r"%LOCALAPPDATA%\go-build", ("GOCACHE",), GO, True),
    Tool("gradle", "Gradle", r"%USERPROFILE%\.gradle", ("GRADLE_USER_HOME",), JAVA, True),
    Tool("maven", "Maven repository", r"%USERPROFILE%\.m2", (), JAVA),
    Tool("nuget", "NuGet packages", r"%USERPROFILE%\.nuget\packages", ("NUGET_PACKAGES",), ("dotnet.exe", "devenv.exe"), True),
    Tool("android-sdk", "Android SDK", r"%LOCALAPPDATA%\Android\Sdk", ("ANDROID_HOME",), JAVA + ("adb.exe", "emulator.exe")),
    Tool("android-avd", "Android emulators", r"%USERPROFILE%\.android", (), JAVA + ("adb.exe", "emulator.exe")),
    Tool("pub-cache", "Flutter pub cache", r"%LOCALAPPDATA%\Pub\Cache", ("PUB_CACHE",), ("dart.exe", "flutter.exe"), True),
    Tool("vscode-extensions", "VS Code extensions", r"%USERPROFILE%\.vscode", (), ("Code.exe",)),
    Tool("vscode-data", "VS Code settings and data", r"%APPDATA%\Code", (), ("Code.exe",)),
    Tool("cursor-extensions", "Cursor extensions", r"%USERPROFILE%\.cursor", (), ("Cursor.exe",)),
    Tool("cursor-data", "Cursor settings and data", r"%APPDATA%\Cursor", (), ("Cursor.exe",)),
    Tool("jetbrains", "JetBrains caches", r"%LOCALAPPDATA%\JetBrains", (), ("idea64.exe", "pycharm64.exe", "webstorm64.exe", "rider64.exe", "clion64.exe")),
    Tool("docker", "Docker Desktop data", r"%LOCALAPPDATA%\Docker", (), DOCKER),
    Tool("huggingface", "Hugging Face models", r"%USERPROFILE%\.cache\huggingface", ("HF_HOME",), PYTHON, True),
    Tool("ollama", "Ollama models", r"%USERPROFILE%\.ollama", (), ("ollama.exe", "ollama app.exe")),
)


def by_id(tool_id):
    for tool in CATALOG:
        if tool.id == tool_id:
            return tool
    raise KeyError(tool_id)
