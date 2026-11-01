import unittest
import winreg

from mixly.environment import RegistryEnv, apply_changes, plan_changes, restore_changes, rewrite_path
from tests.helpers import MemoryEnv

SOURCE = r"C:\Users\me\.cargo"
TARGET = r"D:\Mixly\C\Users\me\.cargo"


class RewriteTests(unittest.TestCase):
    def test_rewrites_only_matching_entries(self):
        value, changed = rewrite_path(r"C:\Windows;C:\Users\me\.cargo\bin;C:\Users\me\.cargo2", SOURCE, TARGET)
        self.assertTrue(changed)
        self.assertEqual(value, r"C:\Windows;D:\Mixly\C\Users\me\.cargo\bin;C:\Users\me\.cargo2")

    def test_keeps_unrelated_paths_untouched(self):
        original = r"%SystemRoot%\system32;;relative\bin"
        value, changed = rewrite_path(original, SOURCE, TARGET)
        self.assertFalse(changed)
        self.assertEqual(value, original)
