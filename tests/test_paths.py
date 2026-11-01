import os
import unittest

from mixly.paths import is_within, long_path, normalize_root, protected_reason, rebase, strip_extended, target_for


class PathTests(unittest.TestCase):
    def test_is_within_ignores_case(self):
        self.assertTrue(is_within(r"C:\Tools\Bin", r"c:\tools"))
        self.assertTrue(is_within(r"C:\Tools", r"C:\Tools"))

    def test_is_within_needs_a_real_boundary(self):
        self.assertFalse(is_within(r"C:\Tools2", r"C:\Tools"))

    def test_long_path_round_trip(self):
        self.assertEqual(long_path(r"C:\a"), "\\\\?\\C:\\a")
        self.assertEqual(strip_extended(long_path(r"C:\a")), r"C:\a")
        self.assertEqual(strip_extended("\\\\?\\UNC\\host\\share"), r"\\host\share")

    def test_normalize_root_adds_a_slash_to_a_drive(self):
        self.assertEqual(normalize_root("D:"), "D:\\")

    def test_target_keeps_the_original_layout(self):
        self.assertEqual(target_for("D:", r"C:\Users\me\.cargo"), r"D:\Mixly\C\Users\me\.cargo")

    def test_rebase(self):
        self.assertEqual(rebase(r"C:\old\bin", r"C:\old", r"D:\new"), r"D:\new\bin")
        self.assertEqual(rebase(r"C:\old", r"C:\old", r"D:\new"), r"D:\new")
