import ctypes
import os
import stat
import threading

from mixly.copier import Cancelled, CopyError, copy_tree, measure, verify_tree, walk
from mixly.links import create_junction, is_junction, link_target
from tests.helpers import TempCase


class CopierTests(TempCase):
    def test_copies_files_folders_and_empty_folders(self):
        self.write("src/a.txt", "one")
        self.write("src/deep/er/b.txt", "two")
        os.makedirs(self.path("src", "empty"))
        manifest = copy_tree(self.path("src"), self.path("dst"))
        verify_tree(manifest, self.path("src"), self.path("dst"))
        self.assertTrue(os.path.isdir(self.path("dst", "empty")))
        with open(self.path("dst", "deep", "er", "b.txt"), encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "two")

    def test_keeps_modified_time_and_attributes(self):
        path = self.write("src/a.txt")
        os.utime(path, (1_600_000_000, 1_600_000_000))
        ctypes.windll.kernel32.SetFileAttributesW(path, 0x2)
        copy_tree(self.path("src"), self.path("dst"))
        info = os.stat(self.path("dst", "a.txt"))
        self.assertEqual(int(info.st_mtime), 1_600_000_000)
        self.assertTrue(info.st_file_attributes & stat.FILE_ATTRIBUTE_HIDDEN)

    def test_copies_a_read_only_file(self):
        os.chmod(self.write("src/a.txt"), 0o444)
        manifest = copy_tree(self.path("src"), self.path("dst"))
        verify_tree(manifest, self.path("src"), self.path("dst"))
        self.assertTrue(os.stat(self.path("dst", "a.txt")).st_file_attributes & stat.FILE_ATTRIBUTE_READONLY)

    def test_handles_paths_over_260_characters(self):
        relative = "/".join(["x" * 40] * 8)
        target = "\\\\?\\" + self.path("src", *relative.split("/"), "file.txt")
        os.makedirs(os.path.dirname(target))
        with open(target, "w", encoding="utf-8") as handle:
            handle.write("deep")
        manifest = copy_tree(self.path("src"), self.path("dst"))
        verify_tree(manifest, self.path("src"), self.path("dst"))
        self.assertEqual(measure(self.path("dst"))[1], 1)

    def test_inner_junction_points_into_the_copy(self):
        self.write("src/real/a.txt")
        create_junction(self.path("src", "real"), self.path("src", "link"))
        manifest = copy_tree(self.path("src"), self.path("dst"))
        verify_tree(manifest, self.path("src"), self.path("dst"))
        self.assertTrue(is_junction(self.path("dst", "link")))
        self.assertEqual(link_target(self.path("dst", "link")).lower(), self.path("dst", "real").lower())

    def test_outside_junction_keeps_its_target_and_isnt_copied(self):
        self.write("outside/big.txt")
        self.write("src/a.txt")
        create_junction(self.path("outside"), self.path("src", "link"))
        copy_tree(self.path("src"), self.path("dst"))
        self.assertEqual(link_target(self.path("dst", "link")).lower(), self.path("outside").lower())
        self.assertEqual(measure(self.path("dst"))[1], 1)

    def test_broken_junction_is_kept_as_is(self):
        self.write("src/a.txt")
        self.write("gone/x.txt")
        create_junction(self.path("gone"), self.path("src", "link"))
        os.remove(self.path("gone", "x.txt"))
        os.rmdir(self.path("gone"))
        manifest = copy_tree(self.path("src"), self.path("dst"))
        verify_tree(manifest, self.path("src"), self.path("dst"))
        self.assertTrue(is_junction(self.path("dst", "link")))
        self.assertFalse(os.path.exists(self.path("gone")))

    def test_measure_doesnt_follow_junctions(self):
        self.write("outside/big.txt", "x" * 100)
        self.write("src/a.txt", "abc")
        create_junction(self.path("outside"), self.path("src", "link"))
        self.assertEqual(measure(self.path("src"))[:2], (3, 1))

    def test_verify_catches_a_damaged_copy(self):
        self.write("src/a.txt", "good")
        manifest = copy_tree(self.path("src"), self.path("dst"))
        with open(self.path("dst", "a.txt"), "w", encoding="utf-8") as handle:
            handle.write("evil")
        with self.assertRaises(CopyError):
            verify_tree(manifest, self.path("src"), self.path("dst"))

    def test_verify_catches_a_missing_file(self):
        self.write("src/a.txt")
        manifest = copy_tree(self.path("src"), self.path("dst"))
        os.remove(self.path("dst", "a.txt"))
        with self.assertRaises(CopyError):
            verify_tree(manifest, self.path("src"), self.path("dst"))

    def test_verify_catches_a_source_edit(self):
        path = self.write("src/a.txt", "one")
        manifest = copy_tree(self.path("src"), self.path("dst"))
        with open(path, "a", encoding="utf-8") as handle:
            handle.write("more")
        with self.assertRaises(CopyError):
            verify_tree(manifest, self.path("src"), self.path("dst"))

    def test_verify_catches_a_new_source_file(self):
        self.write("src/a.txt")
        manifest = copy_tree(self.path("src"), self.path("dst"))
        self.write("src/b.txt")
        with self.assertRaises(CopyError):
            verify_tree(manifest, self.path("src"), self.path("dst"))

    def test_cancel_stops_the_copy(self):
        self.write("src/a.txt")
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(Cancelled):
            copy_tree(self.path("src"), self.path("dst"), cancel=cancel)

    def test_walk_lists_children_once(self):
        self.write("src/a/b.txt")
        names = sorted(relative for relative, _, _ in walk(self.path("src")))
        self.assertEqual(names, ["a", os.path.join("a", "b.txt")])
