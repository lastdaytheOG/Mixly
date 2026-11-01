import os
import time
import tkinter as tk
from unittest import mock

from mixly import content
from mixly.caches import Cache
from mixly.catalog import Tool
from mixly.copier import Cancelled
from mixly.gui import App
from mixly.journal import Journal
from mixly.links import is_junction
from mixly.scan import APPS, CACHES, CAN_CLEAR, DEVELOPER, FILES, GAMES, LARGE, MOVED, STAYS, Found
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
        self.app.allow_same_drive = True
        self.settle()

    def settle(self):
        deadline = time.time() + 30
        while time.time() < deadline:
            self.root.update()
            if not self.app.working and not self.app.sizing and self.app.events.empty():
                return
            time.sleep(0.01)
        self.fail("the window never finished working")

    def test_navigation_changes_the_view_and_buttons(self):
        self.app.select_view(CACHES)
        self.assertEqual(self.app.title_label.cget("text"), CACHES)
        self.assertTrue(self.app.clear_button.winfo_manager())
        self.assertFalse(self.app.move_button.winfo_manager())
        self.app.select_view(MOVED)
        self.assertTrue(self.app.finish_button.winfo_manager())

    def test_search_filters_rows(self):
        self.app.search.set("nothing-like-this")
        self.assertEqual(self.app.tree.get_children(), ())
        self.assertIn("Nothing matches", self.app.empty_label.cget("text"))
        self.app.search.set("too")
        self.assertEqual(self.app.tree.get_children(), ("tool",))

    def test_empty_views_explain_themselves(self):
        self.app.select_view(GAMES)
        self.assertIn("Steam", self.app.empty_label.cget("text"))

    def test_sort_by_clicking_a_heading(self):
        self.write("big/a.bin", "x" * 50)
        self.app._show_found(Found("big", "Aaa", self.path("big"), 50, "ready"))
        self.app._refresh_rows()
        self.assertEqual(self.app.tree.get_children()[0], "big")
        self.app._on_heading("size")
        self.assertEqual(self.app.tree.get_children()[0], "tool")

    def test_heading_tick_selects_everything_shown(self):
        self.app._on_heading("pick")
        self.assertIn("tool", self.app.checked)
        self.app._on_heading("pick")
        self.assertNotIn("tool", self.app.checked)

    def test_something_already_on_the_destination_cant_be_ticked(self):
        self.app.allow_same_drive = False
        self.app._refresh_rows()
        self.app.toggle("tool")
        self.assertNotIn("tool", self.app.checked)
        self.assertIn("already on", self.app.tree.item("tool", "values")[3])
        self.app.allow_same_drive = True

    def test_files_view_browses_and_opens_folders(self):
        self.write("place/sub/inner.txt", "abc")
        self.write("place/top.txt", "abcd")
        self.app.folder = self.path("place")
        self.app.select_view(FILES)
        self.settle()
        rows = self.app.tree.get_children()
        self.assertEqual(set(rows), {self.path("place", "sub"), self.path("place", "top.txt")})
        self.app.browse(self.path("place", "sub"))
        self.assertEqual(self.app.tree.get_children(), (self.path("place", "sub", "inner.txt"),))
        self.app.go_up()
        self.assertEqual(self.app.folder, self.path("place"))

    def test_move_a_file_from_the_files_view(self):
        self.write("place/movie.mkv", "video")
        self.app.folder = self.path("place")
        self.app.select_view(FILES)
        self.settle()
        row = self.path("place", "movie.mkv")
        self.app.toggle(row)
        original = content.move_item
        with mock.patch("mixly.actions.content.move_item", side_effect=lambda path, root, journal, progress, cancel: original(path, root, journal, progress, cancel, True)):
            self.app.start_move()
            self.settle()
        self.assertFalse(os.path.exists(row))
        self.assertTrue(os.path.exists(self.path("dest", "movie.mkv")))
        self.assertEqual(self.app.tree.get_children(), ())
        self.app.select_view(MOVED)
        rows = self.app.tree.get_children()
        self.assertEqual(len(rows), 1)
        self.app.toggle(rows[0])
        self.app.start_undo()
        self.settle()
        self.assertTrue(os.path.exists(row))
        self.assertFalse(os.path.exists(self.path("dest", "movie.mkv")))

    def test_delete_from_the_files_view(self):
        self.write("place/old.zip", "abc")
        self.app.folder = self.path("place")
        self.app.select_view(FILES)
        self.settle()
        row = self.path("place", "old.zip")
        self.app.toggle(row)
        self.app.start_delete(answer="permanent")
        self.settle()
        self.assertFalse(os.path.exists(row))
        self.assertEqual(self.app.tree.get_children(), ())

    def test_cancelling_delete_changes_nothing(self):
        self.write("place/old.zip", "abc")
        self.app.folder = self.path("place")
        self.app.select_view(FILES)
        self.settle()
        row = self.path("place", "old.zip")
        self.app.toggle(row)
        with mock.patch.object(self.app, "_confirm", return_value=None):
            self.app.start_delete()
        self.settle()
        self.assertTrue(os.path.exists(row))

    def test_uninstall_uses_the_action(self):
        found = Found("app:1", "App", self.path("app"), 1, "ready", category=APPS)
        with mock.patch("mixly.gui.actions.uninstall", return_value="Opened it.") as uninstall:
            self.app.start_uninstall([found])
        uninstall.assert_called_once()
        self.assertIn("Opened it", self.app.log.get("1.0", "end"))

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
