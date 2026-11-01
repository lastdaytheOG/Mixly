import os
from unittest import mock

from mixly import preflight, volumes
from mixly.catalog import Tool
from mixly.journal import Journal
from mixly.links import create_junction
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

    def test_mixlys_own_python_is_refused(self):
        with mock.patch.object(preflight, "_own_paths", return_value=[self.path("src", "python.exe")]):
            self.assertTrue(any("in use by Mixly" in problem for problem in self.run_check().problems))
