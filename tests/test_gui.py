import os
import time
import tkinter as tk
from unittest import mock

from mixly.caches import Cache
from mixly.catalog import Tool
from mixly.copier import Cancelled
from mixly.gui import App
from mixly.journal import Journal
from mixly.links import is_junction
from mixly.scan import CACHES, CAN_CLEAR, DEVELOPER, GAMES, LARGE, STAYS, Found
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

    def test_move_everything_skips_what_wont_fit(self):
        self.write("big/a.bin", "x" * 1000)
        self.app._show_found(Found("big", "Big", self.path("big"), 1000, "ready"))
        with mock.patch("mixly.gui.volumes.free_bytes", return_value=100):
            self.app.start_move_everything(ask=False)
            self.settle()
        self.assertTrue(is_junction(self.tool.source))
        self.assertFalse(is_junction(self.path("big")))
        self.assertIn("doesn't fit", self.app.log.get("1.0", "end"))

    def test_stop_pauses_and_move_continues(self):
        self.app.toggle("tool")
        with mock.patch("mixly.mover.copy_tree", side_effect=Cancelled()):
            self.app.start_move()
            self.settle()
        self.assertEqual(self.journal.records()[0]["state"], "paused")
        self.assertEqual(self.app.rows["tool"].status, "paused")
        self.app.toggle("tool")
        self.app.start_move()
        self.settle()
        self.assertTrue(is_junction(self.tool.source))
        self.assertEqual(self.app.rows["tool"].status, "moved")

    def test_clear_selected_caches(self):
        self.write("cache/a.bin", "abc")
        cache = Cache("one", "One cache", self.path("cache"))
        self.app._show_found(Found("cache:one", "One cache", self.path("cache"), 3, CAN_CLEAR, category=CACHES, cache=cache))
        self.app.show.set(CACHES)
        self.app._refresh_rows()
        self.app.toggle("cache:one")
        self.app.start_clear(ask=False)
        self.settle()
        self.assertEqual(os.listdir(self.path("cache")), [])
        self.assertIn("freed", self.app.log.get("1.0", "end"))

    def test_clear_with_nothing_ticked_deletes_nothing(self):
        self.write("cache/a.bin", "abc")
        self.app.start_clear(ask=False)
        self.settle()
        self.assertEqual(os.listdir(self.path("cache")), ["a.bin"])

    def test_large_folders_appear_and_can_move(self):
        self.write("big/a/one.bin", "x" * 100)
        self.write("big/b/two.bin", "x" * 100)
        self.app.space_root = self.path("big")
        self.app.space_minimum = 50
        self.app.start_space()
        self.settle()
        self.assertEqual(self.app.show.get(), LARGE)
        row = self.path("big")
        self.assertEqual(self.app.rows[row].status, "ready")
        self.app.toggle(row)
        self.app.start_move()
        self.settle()
        self.assertTrue(is_junction(row))
        self.assertEqual(self.app.rows[row].status, "moved")

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
