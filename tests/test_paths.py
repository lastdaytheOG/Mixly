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


class ProtectedTests(unittest.TestCase):
    def test_refuses_a_whole_drive(self):
        self.assertIsNotNone(protected_reason("C:\\"))

    def test_refuses_windows_and_the_program_files_folder(self):
        self.assertIsNotNone(protected_reason(os.environ["windir"]))
        self.assertIsNotNone(protected_reason(os.environ["ProgramFiles"]))
        self.assertIsNotNone(protected_reason(os.environ["ProgramData"]))

    def test_refuses_shared_windows_folders_in_program_files(self):
        for name in ("Common Files", "Windows Defender", "Microsoft Office", "dotnet"):
            self.assertIsNotNone(protected_reason(os.path.join(os.environ["ProgramFiles"], name)), name)

    def test_wsl_itself_stays(self):
        self.assertIsNotNone(protected_reason(os.path.join(os.environ["ProgramFiles"], "WSL")))

    def test_program_files_explains_itself_clearly(self):
        reason = protected_reason(os.environ["ProgramFiles(x86)"])
        self.assertTrue(reason.endswith("belongs to Windows"))

    def test_store_app_data_stays(self):
        self.assertIsNotNone(protected_reason(os.path.join(os.environ["LOCALAPPDATA"], "Packages", "Some.App")))

    def test_refuses_hardware_software(self):
        path = os.path.join(os.environ["ProgramFiles"], "NVIDIA Corporation", "Installer2", "Display.Driver")
        self.assertIn("hardware support", protected_reason(path))

    def test_refuses_microsoft_and_installer_cache_folders(self):
        self.assertIsNotNone(protected_reason(os.path.join(os.environ["LOCALAPPDATA"], "Microsoft", "WinGet", "Packages", "X")))
        self.assertIsNotNone(protected_reason(os.path.join(os.environ["LOCALAPPDATA"], "Package Cache", "{id}")))

    def test_points_store_apps_to_settings(self):
        reason = protected_reason(os.path.join(os.environ["ProgramFiles"], "WindowsApps", "Some.Game"))
        self.assertIn("Windows Settings", reason)
        self.assertIn("Windows Settings", protected_reason(r"C:\XboxGames\Some Game"))

    def test_allows_an_app_in_program_files(self):
        self.assertIsNone(protected_reason(os.path.join(os.environ["ProgramFiles"], "Some App")))
        self.assertIsNone(protected_reason(os.path.join(os.environ["ProgramFiles(x86)"], "Steam", "steamapps", "common", "Game")))

    def test_refuses_the_profile_and_appdata(self):
        self.assertIsNotNone(protected_reason(os.environ["USERPROFILE"]))
        self.assertIsNotNone(protected_reason(os.environ["LOCALAPPDATA"]))
        self.assertIsNotNone(protected_reason(os.environ["APPDATA"]))

    def test_allows_a_tool_folder(self):
        self.assertIsNone(protected_reason(os.path.join(os.environ["USERPROFILE"], ".cargo")))
