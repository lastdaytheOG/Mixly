import os
import threading
from unittest import mock

from mixly import mover
from mixly.catalog import Tool
from mixly.copier import Cancelled, CopyError
from mixly.journal import Journal
from mixly.links import create_junction, is_junction
from tests.helpers import MemoryEnv, TempCase


class MoverCase(TempCase):
    def setUp(self):
        super().setUp()
        self.journal = Journal(self.path("home"))
        self.store = MemoryEnv({"Path": (self.path("src", "bin") + r";C:\keep", 2)})
        self.write("src/bin/tool.txt", "hello")
        self.write("src/data/a.txt", "abc")
        self.source = self.path("src")
        self.root = self.path("dest")

    def move(self, tool=None, **options):
        return mover.move(self.source, self.root, self.journal, self.store, tool, same_drive_ok=True, names=set(), **options)

    def undo(self, record):
        mover.undo(record["id"], self.journal, self.store, names=set())

    def read(self, *parts):
        with open(os.path.join(*parts), encoding="utf-8") as handle:
            return handle.read()


class MoveTests(MoverCase):
    def test_tool_keeps_working_at_its_old_path(self):
        record = self.move()
        self.assertTrue(is_junction(self.source))
        self.assertEqual(self.read(self.source, "bin", "tool.txt"), "hello")
        self.assertEqual(self.read(record["target"], "bin", "tool.txt"), "hello")
        self.assertEqual(record["state"], "moved")

    def test_writes_through_the_old_path_land_on_the_new_drive(self):
        record = self.move()
        self.write("src/new.txt", "fresh")
        self.assertEqual(self.read(record["target"], "new.txt"), "fresh")

    def test_keeps_a_backup_until_finished(self):
        record = self.move()
        self.assertEqual(self.read(record["backup"], "bin", "tool.txt"), "hello")

    def test_path_entries_are_rewritten(self):
        record = self.move()
        self.assertEqual(self.store.get("Path")[0], os.path.join(record["target"], "bin") + r";C:\keep")

    def test_tool_variable_is_set(self):
        record = self.move(Tool("x", "X", self.source, env=("X_HOME",)))
        self.assertEqual(self.store.get("X_HOME")[0], record["target"])

    def test_problems_stop_the_move_before_anything_changes(self):
        tool = Tool("x", "X", self.source, processes=("busy.exe",))
        with self.assertRaises(mover.MoveError):
            mover.move(self.source, self.root, self.journal, self.store, tool, same_drive_ok=True, names={"busy.exe"})
        self.assertFalse(is_junction(self.source))
        self.assertEqual(self.journal.records(), [])

    def test_failed_verification_leaves_the_source_alone(self):
        with mock.patch("mixly.mover.verify_tree", side_effect=CopyError("bad")):
            with self.assertRaises(CopyError):
                self.move()
        self.assertFalse(is_junction(self.source))
        self.assertEqual(self.read(self.source, "bin", "tool.txt"), "hello")
        self.assertFalse(os.path.exists(self.root + "\\Mixly"))
        self.assertEqual(self.journal.records(), [])

    def test_cancel_leaves_the_source_alone(self):
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(Cancelled):
            self.move(cancel=cancel)
        self.assertFalse(is_junction(self.source))
        self.assertEqual(self.journal.records(), [])

    def test_locked_folder_leaves_the_source_alone(self):
        with open(self.path("src", "data", "a.txt"), encoding="utf-8"):
            with self.assertRaises(mover.MoveError):
                self.move()
        self.assertFalse(is_junction(self.source))
        self.assertEqual(self.read(self.source, "data", "a.txt"), "abc")
        self.assertEqual(self.journal.records(), [])

    def test_junction_failure_rolls_back(self):
        with mock.patch("mixly.mover.create_junction", side_effect=OSError("no")):
            with self.assertRaises(OSError):
                self.move()
        self.assertFalse(is_junction(self.source))
        self.assertEqual(self.read(self.source, "bin", "tool.txt"), "hello")
        self.assertFalse(os.path.lexists(self.source + ".mixly-old"))
        self.assertEqual(self.journal.records(), [])

    def test_env_failure_rolls_back(self):
        before = self.store.items()
        with mock.patch("mixly.mover.environment.apply_changes", side_effect=OSError("no")):
            with self.assertRaises(OSError):
                self.move()
        self.assertFalse(is_junction(self.source))
        self.assertEqual(self.store.items()["Path"][0].lower(), before["Path"][0].lower())
        self.assertEqual(self.journal.records(), [])


class UndoTests(MoverCase):
    def test_undo_restores_the_original_layout(self):
        record = self.move()
        self.undo(record)
        self.assertFalse(is_junction(self.source))
        self.assertEqual(self.read(self.source, "bin", "tool.txt"), "hello")
        self.assertFalse(os.path.lexists(record["target"]))
        self.assertFalse(os.path.lexists(record["backup"]))
        self.assertEqual(self.journal.records(), [])

    def test_undo_keeps_changes_made_after_the_move(self):
        record = self.move()
        self.write("src/new.txt", "fresh")
        self.undo(record)
        self.assertEqual(self.read(self.source, "new.txt"), "fresh")

    def test_undo_restores_variables(self):
        tool = Tool("x", "X", self.source, env=("X_HOME",))
        record = self.move(tool)
        with mock.patch("mixly.mover.by_id", return_value=tool):
            self.undo(record)
        self.assertIsNone(self.store.get("X_HOME"))
        self.assertIn(self.path("src", "bin").lower(), self.store.get("Path")[0].lower())

    def test_undo_works_after_finish(self):
        record = self.move()
        mover.finish(record["id"], self.journal)
        self.undo(record)
        self.assertEqual(self.read(self.source, "bin", "tool.txt"), "hello")
        self.assertFalse(is_junction(self.source))

    def test_failed_undo_stays_moved(self):
        record = self.move()
        with mock.patch("mixly.mover.verify_tree", side_effect=CopyError("bad")):
            with self.assertRaises(CopyError):
                self.undo(record)
        self.assertTrue(is_junction(self.source))
        self.assertEqual(self.journal.get(record["id"])["state"], "moved")
        self.assertFalse(os.path.lexists(self.source + ".mixly-restore"))


class FinishTests(MoverCase):
    def test_finish_deletes_only_the_old_copy(self):
        record = self.move()
        done = mover.finish(record["id"], self.journal)
        self.assertFalse(os.path.lexists(record["backup"]))
        self.assertEqual(done["state"], "finished")
        self.assertEqual(self.read(self.source, "bin", "tool.txt"), "hello")

    def test_finish_refuses_when_the_link_is_broken(self):
        record = self.move()
        os.rmdir(self.source)
        with self.assertRaises(mover.MoveError):
            mover.finish(record["id"], self.journal)
        self.assertTrue(os.path.exists(record["backup"]))

    def test_finish_refuses_when_the_link_points_elsewhere(self):
        record = self.move()
        os.rmdir(self.source)
        os.makedirs(self.path("other"))
        create_junction(self.path("other"), self.source)
        with self.assertRaises(mover.MoveError):
            mover.finish(record["id"], self.journal)
        self.assertTrue(os.path.exists(record["backup"]))

    def test_remove_pointer_needs_a_tool_that_follows_its_variable(self):
        record = self.move()
        with self.assertRaises(mover.MoveError):
            mover.finish(record["id"], self.journal, remove_pointer=True)
        self.assertTrue(is_junction(self.source))
        self.assertTrue(os.path.exists(record["backup"]))

    def test_remove_pointer_leaves_nothing_behind(self):
        tool = Tool("x", "X", self.source, env=("X_HOME",), native=True)
        record = self.move(tool)
        with mock.patch("mixly.mover.by_id", return_value=tool):
            done = mover.finish(record["id"], self.journal, remove_pointer=True)
        self.assertFalse(os.path.lexists(self.source))
        self.assertFalse(os.path.lexists(record["backup"]))
        self.assertFalse(done["pointer"])
        self.assertEqual(self.read(record["target"], "bin", "tool.txt"), "hello")

    def test_undo_after_removing_the_pointer(self):
        tool = Tool("x", "X", self.source, env=("X_HOME",), native=True)
        record = self.move(tool)
        with mock.patch("mixly.mover.by_id", return_value=tool):
            mover.finish(record["id"], self.journal, remove_pointer=True)
            self.undo(record)
        self.assertEqual(self.read(self.source, "bin", "tool.txt"), "hello")
        self.assertIsNone(self.store.get("X_HOME"))
