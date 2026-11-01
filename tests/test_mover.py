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
