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


class PlanTests(unittest.TestCase):
    def test_sets_the_tool_variable_and_updates_path(self):
        store = MemoryEnv({"Path": (r"C:\Users\me\.cargo\bin;C:\x", 2)})
        plan = plan_changes(store, SOURCE, TARGET, ("CARGO_HOME",))
        apply_changes(store, plan, SOURCE, TARGET)
        self.assertEqual(store.get("CARGO_HOME")[0], TARGET)
        self.assertEqual(store.get("Path"), (r"D:\Mixly\C\Users\me\.cargo\bin;C:\x", 2))
        self.assertEqual(store.broadcasts, 1)

    def test_updates_other_variables_that_point_inside(self):
        store = MemoryEnv({"MY_TOOL": (r"C:\Users\me\.cargo\tool", 1), "OTHER": (r"C:\y", 1)})
        apply_changes(store, plan_changes(store, SOURCE, TARGET), SOURCE, TARGET)
        self.assertEqual(store.get("MY_TOOL")[0], TARGET + r"\tool")
        self.assertEqual(store.get("OTHER")[0], r"C:\y")

    def test_ignores_relative_values(self):
        store = MemoryEnv({"NAME": ("hello", 1)})
        self.assertEqual(plan_changes(store, SOURCE, TARGET)["values"], [])

    def test_restore_puts_everything_back(self):
        store = MemoryEnv({"Path": (r"C:\Users\me\.cargo\bin", 2), "CARGO_HOME": (SOURCE, 1)})
        original = store.items()
        plan = plan_changes(store, SOURCE, TARGET, ("CARGO_HOME",))
        apply_changes(store, plan, SOURCE, TARGET)
        restore_changes(store, plan, SOURCE, TARGET)
        self.assertEqual(store.items()["CARGO_HOME"], original["CARGO_HOME"])
        self.assertEqual(store.items()["Path"][0].lower(), original["Path"][0].lower())

    def test_restore_removes_a_variable_it_added(self):
        store = MemoryEnv()
        plan = plan_changes(store, SOURCE, TARGET, ("CARGO_HOME",))
        apply_changes(store, plan, SOURCE, TARGET)
        restore_changes(store, plan, SOURCE, TARGET)
        self.assertIsNone(store.get("CARGO_HOME"))

    def test_restore_leaves_a_value_the_user_changed(self):
        store = MemoryEnv()
        plan = plan_changes(store, SOURCE, TARGET, ("CARGO_HOME",))
        apply_changes(store, plan, SOURCE, TARGET)
        store.set("CARGO_HOME", r"E:\mine")
        restore_changes(store, plan, SOURCE, TARGET)
        self.assertEqual(store.get("CARGO_HOME")[0], r"E:\mine")

    def test_restore_keeps_path_entries_added_later(self):
        store = MemoryEnv({"Path": (r"C:\Users\me\.cargo\bin", 2)})
        plan = plan_changes(store, SOURCE, TARGET)
        apply_changes(store, plan, SOURCE, TARGET)
        store.set("Path", store.get("Path")[0] + r";C:\new", 2)
        restore_changes(store, plan, SOURCE, TARGET)
        self.assertTrue(store.get("Path")[0].endswith(r";C:\new"))
        self.assertIn(SOURCE.lower(), store.get("Path")[0].lower())


class RegistryTests(unittest.TestCase):
    subkey = r"Software\MixlyTests"

    def setUp(self):
        self.store = RegistryEnv(self.subkey, broadcast=False)
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, self.subkey)
        except FileNotFoundError:
            pass

    def test_round_trip_keeps_the_value_type(self):
        self.store.set("A", r"%TEMP%\x", winreg.REG_EXPAND_SZ)
        self.assertEqual(self.store.get("A"), (r"%TEMP%\x", winreg.REG_EXPAND_SZ))
        self.assertIn("A", self.store.items())
        self.store.delete("A")
        self.assertIsNone(self.store.get("A"))
