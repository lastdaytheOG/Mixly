import os
import threading
from unittest import mock

from mixly import mover
from mixly.catalog import Tool
from mixly.copier import Cancelled, CopyError
from mixly.journal import Journal
from mixly.links import create_junction, is_junction, remove_tree
from mixly.services import Service, ServiceError
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

    def test_stop_pauses_and_leaves_the_source_alone(self):
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(Cancelled):
            self.move(cancel=cancel)
        self.assertFalse(is_junction(self.source))
        self.assertEqual(self.journal.records()[0]["state"], "paused")

    def test_paused_move_continues_without_recopying(self):
        cancel = threading.Event()
        original = mover.copy_tree
        copied = []

        def stop_midway(source, target, on_bytes, stop, resume):
            manifest = original(source, target, on_bytes, None, resume)
            cancel.set()
            raise Cancelled()

        with mock.patch("mixly.mover.copy_tree", side_effect=stop_midway):
            with self.assertRaises(Cancelled):
                self.move(cancel=cancel)
        paused = self.journal.records()[0]
        with mock.patch("mixly.copier._copy_file", side_effect=lambda *args: copied.append(args)):
            record = self.move()
        self.assertEqual(copied, [])
        self.assertEqual(record["id"], paused["id"])
        self.assertEqual(record["state"], "moved")
        self.assertTrue(is_junction(self.source))
        self.assertEqual(self.read(record["target"], "bin", "tool.txt"), "hello")

    def test_undo_discards_a_paused_move(self):
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(Cancelled):
            self.move(cancel=cancel)
        paused = self.journal.records()[0]
        message = mover.undo(paused["id"], self.journal, self.store, names=set())
        self.assertIn("discarded", message)
        self.assertFalse(os.path.lexists(paused["target"]))
        self.assertEqual(self.read(self.source, "bin", "tool.txt"), "hello")
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

    def test_undo_refuses_while_the_launcher_runs(self):
        record = self.move(Tool("steam:1", "Game", self.source, processes=("steam.exe",)))
        with self.assertRaises(mover.MoveError):
            mover.undo(record["id"], self.journal, self.store, names={"steam.exe"})
        self.assertTrue(is_junction(self.source))

    def test_undo_after_an_uninstall_removes_the_dead_link(self):
        record = self.move()
        mover.finish(record["id"], self.journal)
        remove_tree(record["target"])
        message = mover.undo(record["id"], self.journal, self.store, names=set())
        self.assertIn("already gone", message)
        self.assertFalse(os.path.lexists(self.source))
        self.assertEqual(self.journal.records(), [])

    def test_undo_with_a_lost_copy_restores_the_old_one(self):
        record = self.move()
        remove_tree(record["target"])
        message = mover.undo(record["id"], self.journal, self.store, names=set())
        self.assertIn("old copy was put back", message)
        self.assertEqual(self.read(self.source, "bin", "tool.txt"), "hello")

    def test_undo_waits_when_the_drive_is_missing(self):
        record = self.move()
        record["target"] = r"Q:\Mixly\gone"
        self.journal.put(record)
        with mock.patch("mixly.mover.os.path.exists", return_value=False):
            with self.assertRaises(mover.MoveError):
                mover.undo(record["id"], self.journal, self.store, names=set())
        self.assertTrue(is_junction(self.source))
        self.assertEqual(len(self.journal.records()), 1)

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


class ServiceTests(MoverCase):
    def setUp(self):
        super().setUp()
        self.calls = []
        self.listing = [Service("Thing", self.path("src", "bin", "thing.exe"))]
        for patcher in (
            mock.patch("mixly.preflight.services.list_services", return_value=self.listing),
            mock.patch("mixly.preflight.elevation.is_admin", return_value=True),
            mock.patch("mixly.mover.lock_destination"),
            mock.patch("mixly.mover.services.stop_all", side_effect=self.stop_all),
            mock.patch("mixly.mover.services.start_all", side_effect=self.start_all),
            mock.patch("mixly.mover.services.start_quietly", side_effect=self.start_quietly),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def stop_all(self, names):
        self.calls.append(("stop", list(names)))
        return list(names)

    def start_all(self, names):
        self.calls.append(("start", list(names)))

    def start_quietly(self, names):
        self.calls.append(("quiet", list(names)))

    def test_move_stops_then_restarts_the_service(self):
        record = self.move()
        self.assertEqual(self.calls, [("stop", ["Thing"]), ("start", ["Thing"])])
        self.assertTrue(is_junction(self.source))
        self.assertEqual(record["services"], ["Thing"])
        self.assertEqual(record["stopped_services"], [])

    def test_service_that_wont_stop_changes_nothing(self):
        with mock.patch("mixly.mover.services.stop_all", side_effect=ServiceError("wouldn't stop")):
            with self.assertRaises(mover.MoveError):
                self.move()
        self.assertFalse(is_junction(self.source))
        self.assertEqual(self.journal.records(), [])

    def test_service_that_wont_restart_puts_everything_back(self):
        with mock.patch("mixly.mover.services.start_all", side_effect=ServiceError("wouldn't start")):
            with self.assertRaises(mover.MoveError) as caught:
                self.move()
        self.assertIn("put back", str(caught.exception))
        self.assertFalse(is_junction(self.source))
        self.assertEqual(self.read(self.source, "bin", "tool.txt"), "hello")
        self.assertIn(("quiet", ["Thing"]), self.calls)
        self.assertEqual(self.journal.records(), [])

    def test_another_program_still_open_stops_the_move(self):
        with mock.patch("mixly.mover.processes.running_from", return_value=[self.path("src", "bin", "other.exe")]):
            with self.assertRaises(mover.MoveError):
                mover._check_nothing_else_runs({"source": self.source})

    def test_undo_stops_and_restarts_the_service(self):
        record = self.move()
        self.calls.clear()
        self.undo(record)
        self.assertEqual(self.calls[0], ("stop", ["Thing"]))
        self.assertIn(("quiet", ["Thing"]), self.calls)
        self.assertFalse(is_junction(self.source))

    def test_crash_while_stopped_restarts_on_recovery(self):
        record = self.move()
        record["state"] = "copied"
        record["stopped_services"] = ["Thing"]
        self.journal.put(record)
        os.rmdir(self.source)
        os.rename(record["backup"], self.source)
        mover.recover(self.journal, self.store)
        self.assertIn(("quiet", ["Thing"]), self.calls)
        self.assertEqual(self.journal.records(), [])


class RecoverTests(MoverCase):
    def stop_at(self, target):
        with mock.patch(target, side_effect=KeyboardInterrupt):
            with mock.patch("mixly.mover._rollback"), mock.patch("mixly.mover._clear_target"):
                with mock.patch.object(self.journal, "remove"):
                    with self.assertRaises(KeyboardInterrupt):
                        self.move()

    def assert_put_back(self):
        self.assertEqual(mover.recover(self.journal, self.store)[0].endswith("put back"), True)
        self.assertFalse(is_junction(self.source))
        self.assertEqual(self.read(self.source, "bin", "tool.txt"), "hello")
        self.assertFalse(os.path.lexists(self.source + ".mixly-old"))
        self.assertFalse(os.path.exists(self.root + "\\Mixly"))
        self.assertEqual(self.journal.records(), [])

    def test_crash_during_copy_can_continue(self):
        self.stop_at("mixly.mover.verify_tree")
        message = mover.recover(self.journal, self.store)[0]
        self.assertIn("continue", message)
        self.assertFalse(is_junction(self.source))
        self.assertEqual(self.journal.records()[0]["state"], "paused")
        record = self.move()
        self.assertEqual(record["state"], "moved")
        self.assertTrue(is_junction(self.source))

    def test_crash_after_the_rename(self):
        self.stop_at("mixly.mover.create_junction")
        self.assertFalse(os.path.lexists(self.source))
        self.assert_put_back()

    def test_crash_while_setting_variables(self):
        self.stop_at("mixly.mover.environment.apply_changes")
        self.assertTrue(is_junction(self.source))
        self.assert_put_back()

    def test_crash_during_undo_copy_stays_moved(self):
        record = self.move()
        record["previous_state"] = "moved"
        record["state"] = "restoring"
        self.journal.put(record)
        self.write("src.mixly-restore/partial.txt")
        message = mover.recover(self.journal, self.store)[0]
        self.assertTrue(message.endswith("stays moved"))
        self.assertTrue(is_junction(self.source))
        self.assertFalse(os.path.lexists(self.source + ".mixly-restore"))
        self.assertEqual(self.journal.get(record["id"])["state"], "moved")

    def test_crash_during_undo_swap_completes(self):
        record = self.move()
        record["previous_state"] = "moved"
        record["state"] = "restoring"
        self.journal.put(record)
        self.write("src.mixly-restore/bin/tool.txt", "hello")
        os.rmdir(self.source)
        message = mover.recover(self.journal, self.store)[0]
        self.assertTrue(message.endswith("interrupted undo"))
        self.assertEqual(self.read(self.source, "bin", "tool.txt"), "hello")
        self.assertFalse(os.path.lexists(record["target"]))
        self.assertEqual(self.journal.records(), [])

    def test_nothing_to_recover(self):
        self.move()
        self.assertEqual(mover.recover(self.journal, self.store), [])
