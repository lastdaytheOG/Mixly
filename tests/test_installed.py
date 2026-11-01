import json
import os
import winreg
from types import SimpleNamespace
from unittest import mock

from mixly.installed import app_root, find_apps, icon_folder, location_of, program_files_folders, shortcuts
from tests.helpers import TempCase

ROOT = r"Software\MixlyTests\Uninstall"


class InstalledTests(TempCase):
    def setUp(self):
        super().setUp()
        winreg.CreateKey(winreg.HKEY_CURRENT_USER, ROOT).Close()
        self.names = []
        self.addCleanup(self.clean_registry)

    def clean_registry(self):
        for name in self.names:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, f"{ROOT}\\{name}")
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, ROOT)
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, r"Software\MixlyTests")

    def add(self, name, **values):
        self.names.append(name)
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, f"{ROOT}\\{name}") as key:
            for field, value in values.items():
                kind = winreg.REG_DWORD if isinstance(value, int) else winreg.REG_SZ
                winreg.SetValueEx(key, field, 0, kind, value)

    def found(self):
        return find_apps(((winreg.HKEY_CURRENT_USER, ROOT),))

    def test_icon_folder(self):
        self.assertEqual(icon_folder(r'"C:\App\app.exe",0'), r"C:\App")
        self.assertEqual(icon_folder(r"C:\App\app.ico"), "")

    def test_location_prefers_install_location(self):
        self.assertEqual(location_of({"InstallLocation": "C:\\App\\", "DisplayIcon": r"C:\Other\a.exe"}), r"C:\App")
        self.assertEqual(location_of({"DisplayIcon": r"C:\Other\a.exe"}), r"C:\Other")

    def test_app_root_climbs_out_of_subfolders(self):
        self.assertEqual(app_root(r"C:\Program Files\Android\Android Studio\bin"), r"C:\Program Files\Android\Android Studio")
        self.assertEqual(app_root(r"D:\obs-studio\bin\64bit"), r"D:\obs-studio")
        self.assertEqual(app_root(r"C:\Vendor\Browser\Application"), r"C:\Vendor\Browser")
        self.assertEqual(app_root(r"C:\Vendor\Service\5.1.2609.9"), r"C:\Vendor\Service")
        self.assertEqual(app_root(r"C:\Program Files\WinRAR"), r"C:\Program Files\WinRAR")

    def test_app_root_never_climbs_to_a_protected_folder(self):
        self.assertEqual(app_root(r"C:\bin"), r"C:\bin")
        self.assertEqual(app_root(os.path.join(os.environ["ProgramFiles"], "bin")), os.path.join(os.environ["ProgramFiles"], "bin"))

    def test_discovery_adds_apps_from_shortcuts_and_program_folders(self):
        os.makedirs(self.path("Listed"))
        self.write("Resolve/Resolve.exe")
        self.write("Tools/bin/tool.exe")
        os.makedirs(self.path("nodejs"))
        self.add("one", DisplayName="Listed App", InstallLocation=self.path("Listed"))
        shortcut_list = [
            {"name": "DaVinci Resolve", "target": self.path("Resolve", "Resolve.exe")},
            {"name": "Tool", "target": self.path("Tools", "bin", "tool.exe")},
            {"name": "Uninstall", "target": self.path("Listed", "uninstall.exe")},
            {"name": "Docs", "target": self.path("Resolve", "guide.pdf")},
            {"name": "Duplicate", "target": self.path("Listed", "app.exe")},
        ]
        with mock.patch("mixly.installed.shortcuts", return_value=shortcut_list):
            with mock.patch("mixly.installed.app_paths", return_value=[]):
                with mock.patch("mixly.installed.program_files_folders", return_value=[("nodejs", self.path("nodejs")), ("Listed", self.path("Listed"))]):
                    apps = find_apps(((winreg.HKEY_CURRENT_USER, ROOT),), discover=True)
        self.assertEqual(sorted(app.name for app in apps), ["DaVinci Resolve", "Listed App", "Tool", "nodejs"])
        tool = next(app for app in apps if app.name == "Tool")
        self.assertEqual(tool.source, self.path("Tools"))
        self.assertTrue(all(app.id.startswith("app:") for app in apps))

    def test_shortcuts_parses_powershell_output(self):
        output = json.dumps({"name": "One", "target": "C:\\One\\one.exe"})
        result = SimpleNamespace(returncode=0, stdout=output)
        self.assertEqual(shortcuts(lambda script: result), [{"name": "One", "target": "C:\\One\\one.exe"}])
        self.assertEqual(shortcuts(lambda script: SimpleNamespace(returncode=1, stdout="")), [])
        self.assertEqual(shortcuts(lambda script: SimpleNamespace(returncode=0, stdout="not json")), [])

    def test_program_files_folders_skips_protected_ones(self):
        os.makedirs(self.path("pf", "SomeApp"))
        self.write("pf/file.txt")
        found = program_files_folders([self.path("pf")])
        self.assertEqual(found, [("SomeApp", self.path("pf", "SomeApp"))])

    def test_finds_an_app(self):
        os.makedirs(self.path("App"))
        self.add("one", DisplayName="My App", InstallLocation=self.path("App"))
        self.assertEqual([(app.id, app.name, app.source) for app in self.found()], [("app:one", "My App", self.path("App"))])

    def test_skips_system_components_updates_and_missing_folders(self):
        os.makedirs(self.path("App"))
        self.add("a", DisplayName="Hidden", InstallLocation=self.path("App"), SystemComponent=1)
        self.add("b", DisplayName="Update", InstallLocation=self.path("App"), ParentKeyName="x")
        self.add("c", DisplayName="Gone", InstallLocation=self.path("Nope"))
        self.add("d", InstallLocation=self.path("App"))
        self.assertEqual(self.found(), [])

    def test_skips_protected_folders(self):
        self.add("a", DisplayName="Windows Thing", InstallLocation=os.environ["windir"])
        self.add("b", DisplayName="Shared", InstallLocation=os.path.join(os.environ["ProgramFiles"], "Common Files"))
        self.assertEqual(self.found(), [])

    def test_keeps_the_parent_of_nested_apps(self):
        os.makedirs(self.path("App", "Plugin"))
        self.add("a", DisplayName="Plugin", InstallLocation=self.path("App", "Plugin"))
        self.add("b", DisplayName="App", InstallLocation=self.path("App"))
        self.assertEqual([app.name for app in self.found()], ["App"])
