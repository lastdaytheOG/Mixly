import json
import os
import threading
from unittest import mock

from mixly import launchers
from mixly.catalog import Tool
from mixly.copier import Cancelled, CopyError
from mixly.journal import Journal
from mixly.links import is_junction
from mixly.mover import MoveError
from tests.helpers import TempCase


class SteamCase(TempCase):
    def setUp(self):
        super().setUp()
        self.journal = Journal(self.path("home"))
        self.write("c/steamapps/appmanifest_10.acf", '"installdir" "game"')
        self.write("c/steamapps/common/game/game.exe", "exe")
        self.write("c/steamapps/workshop/appworkshop_10.acf", "w")
        self.write("c/steamapps/workshop/content/10/mod.txt", "mod")
        os.makedirs(self.path("d", "steamapps"))
        self.tool = Tool("steam:10", "Game", self.path("c", "steamapps", "common", "game"), (), ("steam.exe",))

    def move(self, **options):
        options.setdefault("names", set())
        return launchers.move_steam(self.tool, self.path("d"), self.journal, same_drive_ok=True, **options)

    def assert_on_old_drive(self):
        self.assertTrue(os.path.exists(self.path("c", "steamapps", "appmanifest_10.acf")))
        self.assertTrue(os.path.exists(self.path("c", "steamapps", "common", "game", "game.exe")))
        self.assertFalse(os.path.exists(self.path("d", "steamapps", "appmanifest_10.acf")))
        self.assertFalse(os.path.exists(self.path("d", "steamapps", "common", "game")))

    def test_game_and_manifest_move_into_the_library_with_no_link(self):
        record = self.move()
        self.assertTrue(os.path.exists(self.path("d", "steamapps", "common", "game", "game.exe")))
        self.assertTrue(os.path.exists(self.path("d", "steamapps", "appmanifest_10.acf")))
        self.assertTrue(os.path.exists(self.path("d", "steamapps", "workshop", "content", "10", "mod.txt")))
        self.assertTrue(os.path.exists(self.path("d", "steamapps", "workshop", "appworkshop_10.acf")))
        self.assertFalse(os.path.exists(self.path("c", "steamapps", "appmanifest_10.acf")))
        self.assertFalse(os.path.lexists(self.tool.source))
        self.assertFalse(record["pointer"])

    def test_old_copies_stay_hidden_until_finish(self):
        record = self.move()
        self.assertTrue(os.path.exists(self.tool.source + ".mixly-old"))
        self.assertTrue(os.path.exists(self.path("c", "steamapps", "appmanifest_10.acf.mixly-old")))
        launchers.finish(record["id"], self.journal)
        self.assertFalse(os.path.exists(self.tool.source + ".mixly-old"))
        self.assertFalse(os.path.exists(self.path("c", "steamapps", "appmanifest_10.acf.mixly-old")))
        self.assertEqual(self.journal.get(record["id"])["state"], "finished")

    def test_steam_running_stops_the_move(self):
        with self.assertRaises(MoveError) as caught:
            self.move(names={"steam.exe"})
        self.assertIn("close steam.exe", str(caught.exception))
        self.assert_on_old_drive()

    def test_failed_copy_changes_nothing(self):
        with mock.patch("mixly.mover.verify_tree", side_effect=CopyError("bad")):
            with self.assertRaises(CopyError):
                self.move()
        self.assert_on_old_drive()
        self.assertEqual(self.journal.records(), [])

    def test_stop_pauses_then_continues(self):
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(Cancelled):
            self.move(cancel=cancel)
        self.assertEqual(self.journal.records()[0]["state"], "paused")
        self.assertTrue(os.path.exists(self.tool.source))
        record = self.move()
        self.assertEqual(record["state"], "moved")

    def test_undo_brings_everything_back_including_updates(self):
        record = self.move()
        self.write("d/steamapps/common/game/patch.txt", "update")
        message = launchers.undo(record["id"], self.journal, names=set())
        self.assertIn("back", message)
        self.assert_on_old_drive()
        self.assertTrue(os.path.exists(self.path("c", "steamapps", "common", "game", "patch.txt")))
        self.assertTrue(os.path.exists(self.path("c", "steamapps", "workshop", "content", "10", "mod.txt")))
        self.assertFalse(os.path.exists(self.tool.source + ".mixly-old"))
        self.assertEqual(self.journal.records(), [])

    def test_undo_after_finish(self):
        record = self.move()
        launchers.finish(record["id"], self.journal)
        launchers.undo(record["id"], self.journal, names=set())
        self.assert_on_old_drive()

    def test_recover_from_a_crash_during_the_switch(self):
        record = self.move()
        record["state"] = "switching"
        self.journal.put(record)
        self.assertIn("put back", launchers.recover(self.journal)[0])
        self.assert_on_old_drive()
        self.assertEqual(self.journal.records(), [])

    def test_recover_finishes_an_interrupted_undo(self):
        record = self.move()
        record["state"] = "restoring"
        self.journal.put(record)
        self.write(self.tool.source.replace(self.base + os.sep, "") + ".mixly-restore/game.exe", "exe")
        self.write("c/steamapps/appmanifest_10.acf.mixly-restore", "m")
        self.assertIn("finished", launchers.recover(self.journal)[0])
        self.assertTrue(os.path.exists(os.path.join(self.tool.source, "game.exe")))
        self.assertEqual(self.journal.records(), [])

    def test_finds_a_library_on_the_chosen_drive(self):
        with mock.patch("mixly.launchers.games.steam_libraries", return_value=[r"C:\Steam", r"D:\SteamLibrary"]):
            self.assertEqual(launchers.steam_library_on("D:", r"C:\Steam"), r"D:\SteamLibrary")
            self.assertIsNone(launchers.steam_library_on("E:", r"C:\Steam"))
