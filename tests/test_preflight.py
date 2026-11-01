import os
import shutil
import subprocess
from unittest import mock

from mixly import elevation, preflight, processes, services, volumes
from mixly.catalog import Tool
from mixly.journal import Journal
from mixly.links import create_junction
from mixly.services import Service
from tests.helpers import TempCase


class PreflightTests(TempCase):
    def setUp(self):
        super().setUp()
        self.journal = Journal(self.path("home"))
        self.write("src/a.txt", "abc")

    def run_check(self, source=None, **options):
        options.setdefault("same_drive_ok", True)
        options.setdefault("names", set())
        return preflight.run(source or self.path("src"), self.path("dest"), self.journal, **options)

    def test_a_normal_folder_passes(self):
        check = self.run_check()
        self.assertEqual(check.problems, [])
        self.assertEqual((check.size, check.files), (3, 1))
        self.assertTrue(check.target.startswith(self.path("dest", "Mixly")))

    def test_same_drive_is_refused(self):
        self.assertTrue(any("already on" in problem for problem in self.run_check(same_drive_ok=False).problems))

    def test_missing_folder_is_refused(self):
        self.assertTrue(self.run_check(self.path("nope")).problems)

    def test_a_file_is_refused(self):
        self.assertTrue(self.run_check(self.path("src", "a.txt")).problems)

    def test_a_link_is_refused(self):
        create_junction(self.path("src"), self.path("link"))
        self.assertTrue(any("already a link" in problem for problem in self.run_check(self.path("link")).problems))

    def test_protected_folder_is_refused(self):
        self.assertTrue(self.run_check(os.environ["windir"]).problems)

    def test_running_process_is_refused(self):
        tool = Tool("t", "T", self.path("src"), processes=("code.exe",))
        check = self.run_check(tool=tool, names={"code.exe"})
        self.assertTrue(any("close Code.exe" in problem or "close code.exe" in problem for problem in check.problems))

    def test_leftover_backup_is_refused(self):
        os.makedirs(self.path("src.mixly-old"))
        self.assertTrue(any("mixly-old" in problem for problem in self.run_check().problems))

    def test_existing_target_is_refused(self):
        os.makedirs(self.run_check().target)
        self.assertTrue(any("already exists" in problem for problem in self.run_check().problems))

    def test_destination_inside_source_is_refused(self):
        check = preflight.run(self.path("src"), self.path("src", "inner"), self.journal, same_drive_ok=True, names=set())
        self.assertTrue(any("inside" in problem for problem in check.problems))

    def test_overlap_with_a_moved_folder_is_refused(self):
        self.write("src/sub/b.txt")
        self.journal.put({"id": "x", "source": self.path("src"), "target": self.path("dest", "x")})
        check = self.run_check(self.path("src", "sub"))
        self.assertTrue(any("overlaps" in problem for problem in check.problems))

    def test_not_enough_space_is_refused(self):
        with mock.patch.object(volumes, "free_bytes", return_value=1):
            self.assertTrue(any("is free" in problem for problem in self.run_check().problems))

    def test_non_ntfs_is_refused(self):
        with mock.patch.object(volumes, "volume_info", return_value=("USB", "exFAT")):
            self.assertTrue(any("NTFS" in problem for problem in self.run_check().problems))

    def test_removable_drive_is_refused(self):
        with mock.patch.object(volumes, "drive_type", return_value=2):
            self.assertTrue(any("internal" in problem for problem in self.run_check().problems))

    def test_a_driver_service_is_refused(self):
        listing = [Service("Thing", self.path("src", "thing.sys"), kind=1)]
        with mock.patch.object(services, "list_services", return_value=listing):
            self.assertTrue(any("early in startup" in problem for problem in self.run_check().problems))

    def test_an_early_start_service_is_refused(self):
        listing = [Service("Thing", self.path("src", "thing.exe"), start=1)]
        with mock.patch.object(services, "list_services", return_value=listing):
            self.assertTrue(any("early in startup" in problem for problem in self.run_check().problems))

    def test_a_normal_service_needs_administrator(self):
        listing = [Service("Thing", self.path("src", "thing.exe"))]
        with mock.patch.object(services, "list_services", return_value=listing):
            with mock.patch.object(elevation, "is_admin", return_value=False):
                self.assertTrue(any("administrator" in problem for problem in self.run_check().problems))

    def test_a_normal_service_is_allowed_for_an_administrator(self):
        listing = [Service("Thing", self.path("src", "thing.exe"))]
        with mock.patch.object(services, "list_services", return_value=listing):
            with mock.patch.object(elevation, "is_admin", return_value=True):
                check = self.run_check()
        self.assertEqual(check.problems, [])
        self.assertEqual(check.services, ["Thing"])

    def test_a_running_service_doesnt_count_as_an_open_program(self):
        path = self.path("src", "thing.exe")
        listing = [Service("Thing", path)]
        with mock.patch.object(services, "list_services", return_value=listing):
            with mock.patch.object(elevation, "is_admin", return_value=True):
                with mock.patch.object(processes, "running_from", return_value=[path]):
                    self.assertEqual(self.run_check().problems, [])

    def test_a_paused_move_can_resume_only_to_the_same_place(self):
        target = self.run_check().target
        os.makedirs(target)
        self.journal.put({"id": "p", "state": "paused", "source": self.path("src"), "target": target})
        check = self.run_check()
        self.assertEqual(check.problems, [])
        self.assertTrue(check.resuming)
        self.journal.put({"id": "p", "state": "paused", "source": self.path("src"), "target": self.path("elsewhere")})
        self.assertTrue(any("paused move" in problem for problem in self.run_check().problems))

    def test_an_app_with_a_driver_is_refused(self):
        self.write("src/drv.sys")
        check = self.run_check(tool=Tool("app:1", "App", self.path("src")))
        self.assertTrue(any("driver drv.sys" in problem for problem in check.problems))

    def test_a_game_can_keep_an_anti_cheat_driver_file(self):
        self.write("src/BattlEye/BEDaisy.sys")
        self.assertEqual(self.run_check(tool=Tool("steam:1", "Game", self.path("src"))).problems, [])

    def test_a_running_program_is_refused(self):
        shutil.copy(os.path.join(os.environ["windir"], "System32", "ping.exe"), self.path("src", "app.exe"))
        process = subprocess.Popen([self.path("src", "app.exe"), "-n", "30", "127.0.0.1"], stdout=subprocess.DEVNULL)
        try:
            self.assertTrue(any("close app.exe" in problem for problem in self.run_check().problems))
        finally:
            process.kill()
            process.wait()

    def test_no_write_access_asks_for_administrator(self):
        with mock.patch.object(elevation, "can_replace", return_value=False):
            self.assertTrue(any("administrator" in problem for problem in self.run_check().problems))

    def test_mixlys_own_python_is_refused(self):
        with mock.patch.object(preflight, "_own_paths", return_value=[self.path("src", "python.exe")]):
            self.assertTrue(any("in use by Mixly" in problem for problem in self.run_check().problems))
