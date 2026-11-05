import os

from mixly.links import create_junction, is_junction, link_target, prune_empty, remove_junction, remove_tree
from tests.helpers import TempCase


class LinkTests(TempCase):
    def test_junction_shows_the_target(self):
        self.write("target/file.txt", "hello")
        create_junction(self.path("target"), self.path("link"))
        self.assertTrue(is_junction(self.path("link")))
        self.assertEqual(link_target(self.path("link")).lower(), self.path("target").lower())
        with open(self.path("link", "file.txt"), encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "hello")

    def test_remove_junction_keeps_the_target(self):
        self.write("target/file.txt")
        create_junction(self.path("target"), self.path("link"))
        remove_junction(self.path("link"))
        self.assertFalse(os.path.lexists(self.path("link")))
        self.assertTrue(os.path.exists(self.path("target", "file.txt")))

    def test_remove_junction_refuses_a_real_folder(self):
        os.makedirs(self.path("real"))
        with self.assertRaises(ValueError):
            remove_junction(self.path("real"))

    def test_remove_tree_never_follows_a_junction(self):
        self.write("outside/keep.txt")
        self.write("tree/inner.txt")
        create_junction(self.path("outside"), self.path("tree", "link"))
        remove_tree(self.path("tree"))
        self.assertFalse(os.path.lexists(self.path("tree")))
        self.assertTrue(os.path.exists(self.path("outside", "keep.txt")))

    def test_remove_tree_clears_read_only_files(self):
        path = self.write("tree/locked.txt")
        os.chmod(path, 0o444)
        remove_tree(self.path("tree"))
        self.assertFalse(os.path.lexists(self.path("tree")))

    def test_remove_tree_ignores_a_missing_folder(self):
        remove_tree(self.path("missing"))

    def test_prune_empty_stops_at_the_limit(self):
        os.makedirs(self.path("root", "a", "b"))
        prune_empty(self.path("root", "a", "b", "gone"), self.path("root"))
        self.assertFalse(os.path.exists(self.path("root", "a")))
        self.assertTrue(os.path.exists(self.path("root")))
    def test_prune_empty_never_touches_siblings_sharing_a_prefix(self):
        os.makedirs(self.path("root_sibling", "inner"))
        prune_empty(self.path("root_sibling", "inner", "file.txt"), self.path("root"))
        self.assertTrue(os.path.exists(self.path("root_sibling", "inner")))
