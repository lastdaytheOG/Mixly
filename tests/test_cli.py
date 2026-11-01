import contextlib
import io
import os
from unittest import mock

from mixly import cli
from mixly.catalog import Tool
from mixly.journal import Journal
from mixly.links import is_junction
from mixly.scan import APPS, GAMES, STAYS, scan
from mixly.services import Service
from tests.helpers import MemoryEnv, TempCase


class ScanTests(TempCase):
    def test_finds_only_what_exists(self):
        self.write("tool/a.txt", "abc")
        tools = (Tool("a", "A", self.path("tool")), Tool("b", "B", self.path("nope")))
        found = scan(Journal(self.path("home")), tools, include_wsl=False, include_installed=False)
        self.assertEqual([(item.id, item.size, item.status) for item in found], [("a", 3, "ready")])

    def test_a_folder_with_a_service_stays_put(self):
        self.write("tool/a.txt")
        tools = (Tool("a", "A", self.path("tool")),)
        with mock.patch("mixly.scan.services.list_services", return_value=[Service("Thing", self.path("tool", "t.exe"))]):
            found = scan(Journal(self.path("home")), tools, include_wsl=False, include_installed=False)
        self.assertEqual(found[0].status, STAYS)
        self.assertIn("Thing", found[0].reason)

    def test_an_app_with_a_driver_file_stays_put(self):
        self.write("app/drv.sys")
        with mock.patch("mixly.scan.games.all_games", return_value=[]):
            with mock.patch("mixly.scan.installed.find_apps", return_value=[Tool("app:1", "App", self.path("app"))]):
                found = scan(Journal(self.path("home")), (), include_wsl=False)
        self.assertEqual(found[0].status, STAYS)
        self.assertIn("drv.sys", found[0].reason)

    def test_something_on_another_drive_isnt_ready(self):
        self.write("tool/a.txt")
        with mock.patch("mixly.scan.volumes.drive_of", return_value="D:"):
            found = scan(Journal(self.path("home")), (Tool("a", "A", self.path("tool")),), include_wsl=False, include_installed=False)
        self.assertEqual(found[0].status, "already on D:")

    def test_finds_games_and_apps_and_skips_duplicates(self):
        self.write("game/a.txt")
        self.write("app/b.txt")
        game = Tool("steam:1", "Game", self.path("game"))
        same_game = Tool("app:1", "Game entry", self.path("game"))
        app = Tool("app:2", "App", self.path("app"))
        with mock.patch("mixly.scan.games.all_games", return_value=[game]):
            with mock.patch("mixly.scan.installed.find_apps", return_value=[same_game, app]):
                found = scan(Journal(self.path("home")), (), include_wsl=False)
        self.assertEqual([(item.id, item.category) for item in found], [("steam:1", GAMES), ("app:2", APPS)])


class CliTests(TempCase):
    def setUp(self):
        super().setUp()
        self.write("tool/a.txt", "abc")
        self.store = MemoryEnv()
        for patcher in (
            mock.patch.dict(os.environ, {"MIXLY_HOME": self.path("home")}),
            mock.patch("mixly.cli.RegistryEnv", return_value=self.store),
            mock.patch("mixly.preflight._check_root"),
            mock.patch("mixly.processes.running_names", return_value=set()),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def run_cli(self, *arguments):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            code = cli.main(list(arguments))
        return code, output.getvalue()

    def test_full_flow_with_a_custom_folder(self):
        code, _ = self.run_cli("move", "--path", self.path("tool"), "--to", self.path("dest"), "--yes")
        self.assertEqual(code, 0)
        self.assertTrue(is_junction(self.path("tool")))
        record = Journal(self.path("home")).records()[0]
        code, output = self.run_cli("status")
        self.assertIn(record["id"], output)
        code, output = self.run_cli("finish", "--yes")
        self.assertEqual(code, 0)
        self.assertIn("link kept", output)
        self.assertFalse(os.path.exists(record["backup"]))
        code, _ = self.run_cli("undo", record["id"])
        self.assertEqual(code, 0)
        self.assertFalse(is_junction(self.path("tool")))
        self.assertEqual(Journal(self.path("home")).records(), [])

    def test_remove_links_keeps_the_link_a_tool_needs(self):
        self.run_cli("move", "--path", self.path("tool"), "--to", self.path("dest"), "--yes")
        record = Journal(self.path("home")).records()[0]
        code, output = self.run_cli("finish", "--remove-links", "--yes")
        self.assertEqual(code, 0)
        self.assertIn("link kept", output)
        self.assertTrue(is_junction(self.path("tool")))
        self.assertFalse(os.path.exists(record["backup"]))

    def test_failed_move_returns_an_error_code(self):
        code, output = self.run_cli("move", "--path", self.path("nope"), "--to", self.path("dest"), "--yes")
        self.assertEqual(code, 1)
        self.assertIn("not moved", output)

    def test_unknown_undo_id_returns_an_error_code(self):
        self.assertEqual(self.run_cli("undo", "nothing")[0], 1)

    def test_answering_no_changes_nothing(self):
        with mock.patch("builtins.input", return_value="n"):
            code, _ = self.run_cli("move", "--path", self.path("tool"), "--to", self.path("dest"))
        self.assertEqual(code, 1)
        self.assertFalse(is_junction(self.path("tool")))
