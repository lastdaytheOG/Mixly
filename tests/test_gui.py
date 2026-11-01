import os
import time
import tkinter as tk
from unittest import mock

from mixly.catalog import Tool
from mixly.gui import App
from mixly.journal import Journal
from mixly.links import is_junction
from mixly.scan import DEVELOPER, GAMES, STAYS, Found
from tests.helpers import MemoryEnv, TempCase


class GuiTests(TempCase):
    def setUp(self):
        super().setUp()
        self.write("tool/a.txt", "abc")
        self.tool = Tool("tool", "Tool", self.path("tool"))
        self.journal = Journal(self.path("home"))
        for patcher in (
            mock.patch("mixly.preflight._check_root"),
            mock.patch("mixly.processes.running_names", return_value=set()),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.app = App(self.root, self.journal, MemoryEnv(), (self.tool,), include_wsl=False, include_installed=False)
        self.app.selected_root = lambda: self.path("dest")
        self.settle()

    def settle(self):
        deadline = time.time() + 30
        while time.time() < deadline:
            self.root.update()
            if not self.app.working and self.app.events.empty():
                return
            time.sleep(0.01)
        self.fail("the window never finished working")

    def test_scan_lists_the_tool(self):
        self.assertEqual(self.app.rows["tool"].status, "ready")

    def test_move_finish_and_undo(self):
        self.app.toggle("tool")
        self.app.start_move()
        self.settle()
        self.assertTrue(is_junction(self.tool.source))
        self.assertEqual(self.app.rows["tool"].status, "moved")
        record = self.journal.records()[0]
        self.app.start_finish(ask=False)
        self.settle()
        self.assertFalse(os.path.exists(record["backup"]))
        self.app.toggle("tool")
        self.app.start_undo()
        self.settle()
        self.assertFalse(is_junction(self.tool.source))
        self.assertEqual(self.app.rows["tool"].status, "ready")
        self.assertEqual(self.journal.records(), [])

    def test_move_everything_takes_all_ready_tools(self):
        self.app.start_move_everything(ask=False)
        self.settle()
        self.assertTrue(is_junction(self.tool.source))
        self.assertEqual(self.app.rows["tool"].status, "moved")

    def test_move_everything_with_nothing_ready_changes_nothing(self):
        self.app.rows["tool"].status = "moved"
        self.app.start_move_everything(ask=False)
        self.settle()
        self.assertFalse(is_junction(self.tool.source))

    def test_finish_can_drop_a_link_the_tool_doesnt_need(self):
        native = Tool("tool", "Tool", self.tool.source, env=("TOOL_HOME",), native=True)
        with mock.patch("mixly.mover.by_id", return_value=native):
            self.app.toggle("tool")
            self.app.start_move()
            self.settle()
            self.app.remove_links.set(True)
            self.app.start_finish(ask=False)
            self.settle()
        self.assertFalse(os.path.lexists(self.tool.source))

    def test_move_everything_only_takes_what_is_shown(self):
        self.write("game/a.txt")
        self.app._show_found(Found("steam:1", "Game", self.path("game"), 1, "ready", category=GAMES))
        self.app.start_move_everything(ask=False)
        self.settle()
        self.assertTrue(is_junction(self.tool.source))
        self.assertFalse(is_junction(self.path("game")))

    def test_filter_shows_one_category(self):
        self.app._show_found(Found("steam:1", "Game", self.path("game"), 1, "ready", category=GAMES))
        self.assertEqual(self.app.tree.get_children(), ("tool",))
        self.app.show.set(GAMES)
        self.app._refresh_rows()
        self.assertEqual(self.app.tree.get_children(), ("steam:1",))

    def test_a_blocked_row_cant_be_ticked_and_says_why(self):
        self.app._show_found(Found("app:1", "App", self.path("app"), 1, STAYS, category=DEVELOPER, reason="it runs a service"))
        self.app.toggle("app:1")
        self.assertNotIn("app:1", self.app.checked)
        self.assertIn("it runs a service", self.app.log.get("1.0", "end"))

    def test_move_with_nothing_ticked_changes_nothing(self):
        self.app.start_move()
        self.settle()
        self.assertFalse(is_junction(self.tool.source))

    def test_failed_move_is_logged(self):
        with mock.patch("mixly.gui.actions.move_found", side_effect=OSError("disk trouble")):
            self.app.toggle("tool")
            self.app.start_move()
            self.settle()
        self.assertIn("disk trouble", self.app.log.get("1.0", "end"))

    def test_added_folder_can_be_moved(self):
        self.write("extra/b.txt")
        self.app.add_path(self.path("extra").replace("\\", "/"))
        self.app.start_move()
        self.settle()
        self.assertTrue(is_junction(self.path("extra")))
