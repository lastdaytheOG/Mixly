import json
from types import SimpleNamespace
from unittest import mock

from mixly import store_apps
from mixly.journal import Journal
from mixly.mover import MoveError
from tests.helpers import TempCase

PACKAGE = "Some.App_1.0.0.0_x64__abc"


class FakeWindows:
    def __init__(self, fails=False, lies=False):
        self.location = r"C:\Program Files\WindowsApps\Some.App"
        self.fails = fails
        self.lies = lies
        self.scripts = []

    def __call__(self, script):
        self.scripts.append(script)
        if script == store_apps.LIST_SCRIPT:
            output = json.dumps({"name": "Some.App", "package": PACKAGE, "location": self.location})
            return SimpleNamespace(returncode=0, stdout=output, stderr="")
        if self.fails:
            return SimpleNamespace(returncode=1, stdout="", stderr="This app can't be moved\nmore detail")
        if not self.lies:
            drive = script.split("-Volume '")[1][:2]
            self.location = drive + r"\WindowsApps\Some.App"
        return SimpleNamespace(returncode=0, stdout="", stderr="")


class StoreTests(TempCase):
    def setUp(self):
        super().setUp()
        self.journal = Journal(self.path("home"))

    def test_lists_a_single_app(self):
        self.assertEqual(store_apps.list_apps(FakeWindows())[0]["package"], PACKAGE)

    def test_hides_drivers_and_system_parts(self):
        apps = [
            {"name": name, "package": name, "location": "C:\\x"}
            for name in ("NVIDIACorp.NVIDIAControlPanel", "Microsoft.VP9VideoExtensions", "Microsoft.WindowsStore", "Microsoft.Paint", "OpenAI.Codex")
        ]
        result = SimpleNamespace(returncode=0, stdout=json.dumps(apps), stderr="")
        self.assertEqual([app["name"] for app in store_apps.list_apps(lambda script: result)], ["Microsoft.Paint", "OpenAI.Codex"])

    def test_parse_handles_nothing_and_many(self):
        self.assertEqual(store_apps.parse_list(""), [])
        self.assertEqual(len(store_apps.parse_list('[{"name":"a"},{"name":"b"}]')), 2)

    def test_move_uses_windows_and_records_it(self):
        windows = FakeWindows()
        record = store_apps.move(PACKAGE, "Some.App", "D:\\", self.journal, windows)
        self.assertEqual(record["target"], r"D:\WindowsApps\Some.App")
        self.assertTrue(any("Move-AppxPackage" in script for script in windows.scripts))
        self.assertTrue(any("Add-AppxVolume" in script for script in windows.scripts))

    def test_windows_refusing_is_reported(self):
        with self.assertRaises(MoveError) as caught:
            store_apps.move(PACKAGE, "Some.App", "D:\\", self.journal, FakeWindows(fails=True))
        self.assertIn("This app can't be moved", str(caught.exception))
        self.assertEqual(self.journal.records(), [])

    def test_success_without_moving_is_caught(self):
        with self.assertRaises(MoveError):
            store_apps.move(PACKAGE, "Some.App", "D:\\", self.journal, FakeWindows(lies=True))
        self.assertEqual(self.journal.records(), [])

    def test_undo_moves_it_back(self):
        windows = FakeWindows()
        record = store_apps.move(PACKAGE, "Some.App", "D:\\", self.journal, windows)
        store_apps.undo(record["id"], self.journal, windows)
        self.assertTrue(windows.location.startswith("C:"))
        self.assertEqual(self.journal.records(), [])

    def test_already_on_the_drive_is_refused(self):
        windows = FakeWindows()
        windows.location = r"D:\WindowsApps\Some.App"
        with self.assertRaises(MoveError):
            store_apps.move(PACKAGE, "Some.App", "D:\\", self.journal, windows)

    def test_unsafe_package_names_never_reach_powershell(self):
        for name in ("x'; Remove-Item C:\\ -Recurse; '", "a b", "a$(b)"):
            with self.assertRaises(MoveError):
                store_apps.move_script(name, "D:\\")

    def test_unsafe_drive_is_refused(self):
        with mock.patch("mixly.store_apps.volumes.drive_of", return_value="\\\\host"):
            with self.assertRaises(MoveError):
                store_apps._volume("\\\\host\\share")
