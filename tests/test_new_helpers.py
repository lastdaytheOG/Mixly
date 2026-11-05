import os
import unittest
from unittest import mock

from mixly import acl, actions, browser, cli, spacefinder, theme, trash, volumes
from mixly.catalog import Tool
from mixly.copier import copy_file_verified, CopyError
from mixly.journal import Journal
from mixly.links import create_junction
from mixly.mover import MoveError
from mixly.scan import Found
from mixly.sizes import SizeCache
from tests.helpers import TempCase


class ThemeTests(unittest.TestCase):
    def test_oklch_endpoints(self):
        self.assertEqual(theme.oklch(1.0, 0, 145), "#ffffff")
        self.assertEqual(theme.oklch(0.0, 0, 145), "#000000")

    def test_text_is_readable_in_both_themes(self):
        for palette in (theme.LIGHT, theme.DARK):
            for background in (palette.surface, palette.side, palette.raised):
                self.assertGreaterEqual(theme.contrast(palette.ink, background), 4.5, palette.name)
                self.assertGreaterEqual(theme.contrast(palette.muted, background), 4.5, palette.name)
            self.assertGreaterEqual(theme.contrast(palette.on_accent, palette.accent), 4.5, palette.name)
            self.assertGreaterEqual(theme.contrast(palette.ink, palette.selected), 4.5, palette.name)
            self.assertGreaterEqual(theme.contrast(palette.attention, palette.surface), 4.5, palette.name)
            self.assertGreaterEqual(theme.contrast(palette.accent, palette.surface), 4.5, palette.name)

    def test_dark_title_bar_uses_own_hwnd_if_parent_is_zero(self):
        window = mock.Mock()
        window.winfo_id.return_value = 1234
        with mock.patch("ctypes.windll.user32.GetParent", return_value=0):
            with mock.patch("ctypes.windll.dwmapi.DwmSetWindowAttribute", return_value=0) as dwm:
                theme.dark_title_bar(window, True)
                self.assertEqual(dwm.call_args[0][0], 1234)

class SizeCacheTests(TempCase):
    def test_survives_a_restart(self):
        cache = SizeCache(self.base)
        cache.put(r"C:\Tools", 123, "a.sys")
        cache.save()
        self.assertEqual(SizeCache(self.base).get(r"c:\tools"), [123, "a.sys"])

    def test_a_damaged_file_starts_empty(self):
        with open(self.path("sizes.json"), "w", encoding="utf-8") as handle:
            handle.write("not json")
        self.assertIsNone(SizeCache(self.base).get("x"))


class BrowserTests(TempCase):
    def test_lists_folders_first_with_file_sizes(self):
        self.write("place/zeta.txt", "abc")
        self.write("place/alpha/inner.txt")
        entries = browser.list_folder(self.path("place"))
        self.assertEqual([entry.name for entry in entries], ["alpha", "zeta.txt"])
        self.assertTrue(entries[0].is_folder)
        self.assertEqual(entries[1].size, 3)

    def test_hides_links_and_system_files(self):
        self.write("place/a.txt")
        self.write("other/b.txt")
        create_junction(self.path("other"), self.path("place", "link"))
        self.assertEqual([entry.name for entry in browser.list_folder(self.path("place"))], ["a.txt"])

    def test_parent_stops_at_the_drive(self):
        self.assertEqual(browser.parent_of(r"C:\a\b"), r"C:\a")
        self.assertIsNone(browser.parent_of("C:\\"))

    def test_places_include_folders_and_drives(self):
        names = [name for name, _ in browser.places()]
        self.assertIn("Downloads", names)
        self.assertIn(os.environ["SystemDrive"].upper(), names)


class VolumeTests(unittest.TestCase):
    def test_lists_the_system_drive(self):
        letters = [f"{drive.letter}:" for drive in volumes.list_drives(include_removable=True)]
        self.assertIn(os.environ["SystemDrive"].upper(), letters)


class CopyFileTests(TempCase):
    def test_copies_and_keeps_the_date(self):
        path = self.write("a.txt", "abc")
        os.utime(path, (1_600_000_000, 1_600_000_000))
        copy_file_verified(path, self.path("sub", "a.txt"))
        self.assertEqual(int(os.stat(self.path("sub", "a.txt")).st_mtime), 1_600_000_000)

    def test_a_bad_read_back_raises(self):
        path = self.write("a.txt", "abc")
        with mock.patch("mixly.copier._hash_file", return_value="wrong"):
            with self.assertRaises(CopyError):
                copy_file_verified(path, self.path("b.txt"))


class TrashTests(TempCase):
    def test_permanent_delete_doesnt_follow_links(self):
        self.write("keep/a.txt")
        self.write("gone/b.txt")
        create_junction(self.path("keep"), self.path("gone", "link"))
        trash.delete_permanently(self.path("gone"))
        self.assertFalse(os.path.lexists(self.path("gone")))
        self.assertTrue(os.path.exists(self.path("keep", "a.txt")))

    def test_a_very_long_path_is_refused_for_the_bin(self):
        with self.assertRaises(OSError):
            trash.to_recycle_bin("C:\\" + "x" * 300)


class ActionTests(TempCase):
    def setUp(self):
        super().setUp()
        self.journal = Journal(self.path("home"))

    def test_delete_refuses_protected_folders(self):
        found = Found("w", "Windows", os.environ["windir"], 0, "ready")
        with mock.patch("mixly.actions.trash.to_recycle_bin") as recycle:
            with self.assertRaises(MoveError):
                actions.delete_found(found, self.journal)
        recycle.assert_not_called()

    def test_delete_uses_the_recycle_bin_by_default(self):
        path = self.write("a.txt")
        with mock.patch("mixly.actions.trash.to_recycle_bin") as recycle:
            message = actions.delete_found(Found(path, "a.txt", path, 1, "ready"), self.journal)
        recycle.assert_called_once_with(path)
        self.assertTrue(os.path.exists(path))
        self.assertIn("Recycle Bin", message)

    def test_delete_refuses_something_mixly_moved(self):
        path = self.write("tool/a.txt")
        folder = os.path.dirname(path)
        self.journal.put({"id": "x", "kind": "folder", "source": folder, "target": self.path("elsewhere")})
        with self.assertRaises(MoveError):
            actions.delete_found(Found(folder, "tool", folder, 1, "ready"), self.journal, permanently=True)
        self.assertTrue(os.path.exists(path))

    def test_uninstall_runs_the_registered_uninstaller(self):
        found = Found("app:1", "App", "C:\\x", 1, "ready", Tool("app:1", "App", "C:\\x", uninstall='"C:\\x\\unins000.exe"'))
        with mock.patch("mixly.actions.subprocess.Popen") as popen:
            self.assertIn("uninstaller", actions.uninstall(found))
        popen.assert_called_once_with('"C:\\x\\unins000.exe"')

    def test_uninstall_asks_steam_for_a_steam_game(self):
        found = Found("steam:10", "Game", "C:\\x", 1, "ready", Tool("steam:10", "Game", "C:\\x"))
        with mock.patch("mixly.actions.os.startfile") as startfile:
            actions.uninstall(found)
        startfile.assert_called_once_with("steam://uninstall/10")

    def test_uninstall_opens_settings_for_store_apps(self):
        found = Found("store:x", "App", "C:\\x", 0, "ready", package="x")
        with mock.patch("mixly.actions.os.startfile") as startfile:
            actions.uninstall(found)
        startfile.assert_called_once_with(actions.SETTINGS_APPS)

    def test_relocate_back_to_the_original_drive_only_undoes(self):
        record = {"source": r"C:\tool", "target": r"D:\Mixly\C\tool", "kind": "folder", "id": "x"}
        found = Found("tool", "Tool", r"C:\tool", 1, "moved")
        with mock.patch("mixly.actions.undo_record", return_value="back") as undo, mock.patch("mixly.actions.move_found") as move:
            self.assertEqual(actions.relocate(found, record, "C:\\", self.journal, None), "back")
        undo.assert_called_once()
        move.assert_not_called()

    def test_relocate_to_a_third_drive_undoes_then_moves(self):
        record = {"source": r"C:\tool", "target": r"D:\Mixly\C\tool", "kind": "folder", "id": "x"}
        found = Found("tool", "Tool", r"C:\tool", 1, "moved")
        with mock.patch("mixly.actions.undo_record", return_value="back"), mock.patch("mixly.actions.move_found", return_value={"target": r"E:\Mixly\C\tool"}) as move:
            self.assertIn("E:", actions.relocate(found, record, "E:\\", self.journal, None))
        move.assert_called_once()
        self.assertEqual(found.status, "ready")

    def test_reveal_quotes_path_for_explorer(self):
        path = self.write("folder with spaces/file.txt")
        with mock.patch("subprocess.Popen") as popen:
            actions.reveal(path)
            popen.assert_called_once_with(f'explorer /select,"{os.path.abspath(path)}"')

    def test_progress_zero_total_does_not_raise(self):
        progress = cli._Progress()
        progress(0, 0)
        self.assertEqual(progress.last, 0)

    def test_copy_root_permissions_ignores_oserror_on_non_ntfs(self):
        with mock.patch("mixly.acl.read_dacl", side_effect=OSError("Not supported")):
            acl.copy_root_permissions(r"C:\src", r"D:\dst")

class SpaceSpeedTests(TempCase):
    def test_parallel_reading_matches_a_simple_total(self):
        total = 0
        for first in range(3):
            for second in range(3):
                for third in range(2):
                    self.write(f"root/{first}/{second}/{third}/deep/file.bin", "x" * 10)
                    total += 10
        self.write("root/top.bin", "x" * 5)
        tree = spacefinder.read_tree(self.path("root"), 1)
        self.assertEqual(tree.size, total + 5)
        self.assertEqual(len(tree.children), 3)
        self.assertEqual(len(tree.children[0].children), 3)
