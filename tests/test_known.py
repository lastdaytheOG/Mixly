import os
from unittest import mock

from mixly import known
from mixly.journal import Journal
from mixly.mover import MoveError
from tests.helpers import TempCase


class FakeFolders:
    def __init__(self, path, failing=False):
        self.path = path
        self.failing = failing

    def get(self, folder_id):
        return self.path

    def set(self, folder_id, path):
        if self.failing:
            raise OSError("refused")
        self.path = path


class KnownTests(TempCase):
    def setUp(self):
        super().setUp()
        self.write("Downloads/file.txt", "keep")
        self.journal = Journal(self.path("home"))
        self.folders = FakeFolders(self.path("Downloads"))

    def move(self):
        return known.move("downloads", self.path("dest"), self.journal, self.folders, same_drive_ok=True)

    def test_windows_folder_changes_with_no_link_left(self):
        record = self.move()
        self.assertEqual(self.folders.path, record["target"])
        self.assertTrue(os.path.exists(os.path.join(record["target"], "file.txt")))
        self.assertFalse(record["pointer"])
        self.assertEqual(record["state"], "moved")

    def test_old_copy_stays_until_finish(self):
        record = self.move()
        self.assertTrue(os.path.exists(self.path("Downloads", "file.txt")))
        known.finish(record["id"], self.journal, self.folders)
        self.assertFalse(os.path.exists(self.path("Downloads")))
        self.assertTrue(os.path.exists(os.path.join(record["target"], "file.txt")))

    def test_finish_refuses_if_windows_points_elsewhere(self):
        record = self.move()
        self.folders.path = self.path("Other")
        with self.assertRaises(MoveError):
            known.finish(record["id"], self.journal, self.folders)
        self.assertTrue(os.path.exists(self.path("Downloads", "file.txt")))

    def test_undo_keeps_new_files_and_restores_the_location(self):
        record = self.move()
        with open(os.path.join(record["target"], "later.txt"), "w", encoding="utf-8") as handle:
            handle.write("new")
        message = known.undo(record["id"], self.journal, self.folders)
        self.assertIn("back", message)
        self.assertEqual(self.folders.path, self.path("Downloads"))
        self.assertTrue(os.path.exists(self.path("Downloads", "later.txt")))
        self.assertFalse(os.path.exists(record["target"]))
        self.assertEqual(self.journal.records(), [])

    def test_undo_after_finish(self):
        record = self.move()
        known.finish(record["id"], self.journal, self.folders)
        known.undo(record["id"], self.journal, self.folders)
        self.assertTrue(os.path.exists(self.path("Downloads", "file.txt")))

    def test_windows_refusing_changes_nothing(self):
        self.folders.failing = True
        with self.assertRaises(MoveError):
            self.move()
        self.assertTrue(os.path.exists(self.path("Downloads", "file.txt")))
        self.assertFalse(os.path.exists(self.path("dest", "Mixly")))
        self.assertEqual(self.journal.records(), [])

    def test_onedrive_is_refused(self):
        self.write("OneDrive/Documents/a.txt")
        self.folders.path = self.path("OneDrive", "Documents")
        with self.assertRaises(MoveError) as caught:
            self.move()
        self.assertIn("OneDrive", str(caught.exception))
        self.assertEqual(self.journal.records(), [])

    def test_recover_from_a_crash_while_copying(self):
        record = self.move()
        record["state"] = "copying"
        self.journal.put(record)
        self.folders.path = self.path("Downloads")
        self.assertIn("nothing changed", known.recover(self.journal, self.folders)[0])
        self.assertEqual(self.journal.records(), [])

    def test_recover_when_the_switch_had_finished(self):
        record = self.move()
        record["state"] = "switching"
        self.journal.put(record)
        self.assertIn("had finished", known.recover(self.journal, self.folders)[0])
        self.assertEqual(self.journal.records()[0]["state"], "moved")

    def test_recover_from_a_crash_during_undo(self):
        record = self.move()
        record["state"] = "restoring"
        self.journal.put(record)
        self.write("Downloads.mixly-restore/file.txt", "restored")
        self.assertIn("finished", known.recover(self.journal, self.folders)[0])
        self.assertEqual(self.folders.path, self.path("Downloads"))
        with open(self.path("Downloads", "file.txt"), encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "restored")

    def test_reads_real_windows_folders(self):
        for name in known.FOLDERS:
            self.assertTrue(os.path.isabs(known.current_path(name)))
