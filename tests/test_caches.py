import os

from mixly.caches import CACHES, Cache, available, clear, real_path, size_of
from mixly.links import create_junction
from tests.helpers import TempCase


class CacheTests(TempCase):
    def cache(self, **options):
        return Cache("one", "One", self.path("cache"), **options)

    def test_lists_only_caches_with_contents(self):
        self.write("cache/a.bin", "abc")
        os.makedirs(self.path("empty"))
        found = available((self.cache(), Cache("two", "Two", self.path("empty")), Cache("three", "Three", self.path("gone"))))
        self.assertEqual([cache.id for cache in found], ["one"])

    def test_clear_empties_the_folder_but_keeps_it(self):
        self.write("cache/a.bin", "abc")
        self.write("cache/sub/b.bin", "de")
        freed, skipped = clear(self.cache(), set())
        self.assertEqual((freed, skipped), (5, 0))
        self.assertEqual(os.listdir(self.path("cache")), [])

    def test_clear_refuses_while_the_tool_runs(self):
        self.write("cache/a.bin")
        with self.assertRaises(OSError):
            clear(self.cache(processes=("node.exe",)), {"node.exe"})
        self.assertTrue(os.path.exists(self.path("cache", "a.bin")))

    def test_clear_skips_locked_files(self):
        self.write("cache/keep.bin", "abc")
        self.write("cache/gone.bin", "de")
        with open(self.path("cache", "keep.bin"), encoding="utf-8"):
            freed, skipped = clear(self.cache(), set())
        self.assertEqual((freed, skipped), (2, 1))
        self.assertEqual(os.listdir(self.path("cache")), ["keep.bin"])

    def test_clear_follows_a_moved_cache_and_keeps_its_link(self):
        self.write("moved/a.bin", "abc")
        create_junction(self.path("moved"), self.path("cache"))
        self.assertEqual(real_path(self.cache()).lower(), self.path("moved").lower())
        self.assertEqual(size_of(self.cache()), 3)
        clear(self.cache(), set())
        self.assertEqual(os.listdir(self.path("moved")), [])
        self.assertTrue(os.path.lexists(self.path("cache")))

    def test_clear_never_follows_a_link_out_of_the_cache(self):
        self.write("outside/keep.txt")
        self.write("cache/a.bin")
        create_junction(self.path("outside"), self.path("cache", "link"))
        clear(self.cache(), set())
        self.assertTrue(os.path.exists(self.path("outside", "keep.txt")))

    def test_catalog_only_holds_things_that_rebuild(self):
        paths = " ".join(cache.path.lower() for cache in CACHES)
        self.assertNotIn("huggingface", paths)
        self.assertNotIn("%temp%", paths)
        self.assertNotIn(".ollama", paths)
