import contextlib
import io
import os
from unittest import mock

from mixly import cli
from mixly.catalog import Tool
from mixly.journal import Journal
from mixly.links import is_junction
from mixly.scan import scan
from tests.helpers import MemoryEnv, TempCase


class ScanTests(TempCase):
    def test_finds_only_what_exists(self):
        self.write("tool/a.txt", "abc")
        tools = (Tool("a", "A", self.path("tool")), Tool("b", "B", self.path("nope")))
        found = scan(Journal(self.path("home")), tools, include_wsl=False)
        self.assertEqual([(item.id, item.size, item.status) for item in found], [("a", 3, "ready")])


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
