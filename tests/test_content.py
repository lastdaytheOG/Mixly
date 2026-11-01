import os
import threading
from unittest import mock

from mixly import content
from mixly.copier import Cancelled, CopyError
from mixly.journal import Journal
from mixly.links import create_junction
from mixly.mover import MoveError
from tests.helpers import TempCase


class ContentCase(TempCase):
    def setUp(self):
        super().setUp()
        self.journal = Journal(self.path("home"))
        self.write("Downloads/movie.mkv", "video")
        self.write("Downloads/album/one.mp3", "one")
        self.write("Downloads/album/two.mp3", "two")
        self.file = self.path("Downloads", "movie.mkv")
        self.folder = self.path("Downloads", "album")

    def move(self, path, **options):
        return content.move_item(path, self.path("dest"), self.journal, same_drive_ok=True, **options)


class TargetTests(ContentCase):
    def test_a_drive_keeps_the_parent_folder_name(self):
        self.assertEqual(content.content_target("D:\\", r"C:\Users\me\Downloads\a.zip"), r"D:\Downloads\a.zip")

    def test_a_chosen_folder_takes_the_item_directly(self):
        self.assertEqual(content.content_target(r"D:\Media", r"C:\Users\me\Downloads\a.zip"), r"D:\Media\a.zip")

    def test_free_name_never_overwrites(self):
        self.write("x/a.txt")
        self.assertEqual(content.free_name(self.path("x", "b.txt")), self.path("x", "b.txt"))
        self.assertEqual(content.free_name(self.path("x", "a.txt")), self.path("x", "a (2).txt"))
        self.write("x/a (2).txt")
        self.assertEqual(content.free_name(self.path("x", "a.txt")), self.path("x", "a (3).txt"))


class MoveTests(ContentCase):
    def test_moves_a_file_and_leaves_nothing_behind(self):
        record = self.move(self.file)
        self.assertFalse(os.path.lexists(self.file))
        self.assertFalse(os.path.lexists(self.file + ".mixly-old"))
        with open(record["target"], encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "video")
        self.assertEqual(record["state"], "finished")

    def test_moves_a_folder_and_leaves_nothing_behind(self):
        record = self.move(self.folder)
        self.assertFalse(os.path.lexists(self.folder))
        self.assertEqual(sorted(os.listdir(record["target"])), ["one.mp3", "two.mp3"])

    def test_an_existing_file_is_never_overwritten(self):
        self.write("dest/movie.mkv", "already here")
        record = self.move(self.file)
        self.assertTrue(record["target"].endswith("movie (2).mkv"))
        with open(self.path("dest", "movie.mkv"), encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "already here")

    def test_same_drive_is_refused(self):
        with self.assertRaises(MoveError):
            content.move_item(self.file, self.path("dest"), self.journal)
        self.assertTrue(os.path.exists(self.file))

    def test_not_enough_space_changes_nothing(self):
        with mock.patch("mixly.content.volumes.free_bytes", return_value=1):
            with self.assertRaises(MoveError):
                self.move(self.file)
        self.assertTrue(os.path.exists(self.file))
        self.assertEqual(self.journal.records(), [])

    def test_failed_verification_keeps_the_original(self):
        with mock.patch("mixly.content.verify_tree", side_effect=CopyError("bad")):
            with self.assertRaises(CopyError):
                self.move(self.folder)
        self.assertTrue(os.path.exists(os.path.join(self.folder, "one.mp3")))
        self.assertFalse(os.path.exists(self.path("dest", "album")))
        self.assertEqual(self.journal.records(), [])

    def test_a_locked_file_keeps_the_original(self):
        with open(self.file, encoding="utf-8"):
            with self.assertRaises(MoveError):
                self.move(self.file)
        self.assertTrue(os.path.exists(self.file))
        self.assertFalse(os.path.exists(self.path("dest", "movie.mkv")))
        self.assertEqual(self.journal.records(), [])

    def test_stop_keeps_the_original(self):
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(Cancelled):
            self.move(self.file, cancel=cancel)
        self.assertTrue(os.path.exists(self.file))
        self.assertEqual(self.journal.records(), [])

    def test_a_link_is_refused(self):
        create_junction(self.folder, self.path("Downloads", "link"))
        with self.assertRaises(MoveError):
            self.move(self.path("Downloads", "link"))

    def test_a_windows_folder_itself_is_refused(self):
        with mock.patch("mixly.content.known_folder_paths", return_value=[self.path("Downloads")]):
            with self.assertRaises(MoveError) as caught:
                self.move(self.path("Downloads"))
        self.assertIn("what's inside", str(caught.exception))

    def test_what_is_inside_a_windows_folder_is_fine(self):
        with mock.patch("mixly.content.known_folder_paths", return_value=[self.path("Downloads")]):
            self.assertEqual(self.move(self.file)["state"], "finished")

    def test_protected_folders_are_refused(self):
        self.assertIsNotNone(content.problem_with(os.environ["windir"], self.journal))

    def test_something_mixly_already_moved_is_refused(self):
        self.journal.put({"id": "x", "kind": "folder", "source": self.folder, "target": self.path("other")})
        self.assertIn("overlaps", content.problem_with(self.folder, self.journal))


class UndoTests(ContentCase):
    def test_undo_brings_a_file_back(self):
        record = self.move(self.file)
        message = content.undo(record["id"], self.journal)
        self.assertIn("back", message)
        self.assertTrue(os.path.exists(self.file))
        self.assertFalse(os.path.exists(record["target"]))
        self.assertEqual(self.journal.records(), [])

    def test_undo_brings_a_folder_back(self):
        record = self.move(self.folder)
        content.undo(record["id"], self.journal)
        self.assertEqual(sorted(os.listdir(self.folder)), ["one.mp3", "two.mp3"])

    def test_undo_never_overwrites_a_new_file(self):
        record = self.move(self.file)
        self.write("Downloads/movie.mkv", "a new one")
        content.undo(record["id"], self.journal)
        with open(self.file, encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "a new one")
        self.assertTrue(os.path.exists(self.path("Downloads", "movie (2).mkv")))

    def test_undo_when_the_moved_copy_is_gone(self):
        record = self.move(self.file)
        os.remove(record["target"])
        self.assertIn("no longer", content.undo(record["id"], self.journal))
        self.assertEqual(self.journal.records(), [])


class RecoverTests(ContentCase):
    def test_crash_while_copying_keeps_the_original(self):
        record = self.move(self.file)
        os.rename(record["target"], self.file)
        self.write("dest/movie.mkv", "par")
        record["state"] = "copying"
        self.journal.put(record)
        self.assertIn("nothing changed", content.recover(self.journal)[0])
        self.assertFalse(os.path.exists(record["target"]))
        self.assertTrue(os.path.exists(self.file))

    def test_crash_while_removing_finishes_the_job(self):
        record = self.move(self.file)
        self.write("Downloads/movie.mkv.mixly-old", "old")
        record["state"] = "removing"
        self.journal.put(record)
        self.assertIn("finished", content.recover(self.journal)[0])
        self.assertFalse(os.path.exists(self.file + ".mixly-old"))
        self.assertEqual(self.journal.get(record["id"])["state"], "finished")
