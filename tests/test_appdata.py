import os
from unittest import mock

from mixly.appdata import data_folders, save_folders
from mixly.catalog import Tool
from mixly.journal import Journal
from mixly.scan import DATA, scan
from tests.helpers import TempCase


class AppDataTests(TempCase):
    def test_lists_app_folders_and_skips_system_ones(self):
        for name in ("Telegram", "Microsoft", "Temp", "Packages", "Programs", ".hidden"):
            os.makedirs(self.path("local", name))
        self.write("local/file.txt")
        tools = data_folders([self.path("local")])
        self.assertEqual([(tool.id, tool.name) for tool in tools], [("data:Telegram", "Telegram data")])

    def test_duplicate_folders_across_parents_are_disambiguated(self):
        os.makedirs(self.path("local", "Google"))
        os.makedirs(self.path("roaming", "Google"))
        tools = data_folders([self.path("local"), self.path("roaming")])
        self.assertEqual(
            [(tool.id, tool.name) for tool in tools],
            [("data:Google", "Google (local) data"), ("data:Google:roaming", "Google (roaming) data")],
        )
    def test_finds_save_folders(self):
        os.makedirs(self.path("home", "Saved Games"))
        os.makedirs(self.path("home", "Documents", "My Games"))
        self.assertEqual(len(save_folders(self.path("home"))), 2)

    def test_skips_missing_save_folders(self):
        os.makedirs(self.path("home"))
        self.assertEqual(save_folders(self.path("home")), [])

    def run_scan(self, tools, data):
        with mock.patch("mixly.scan.appdata.save_folders", return_value=[]):
            with mock.patch("mixly.scan.appdata.data_folders", return_value=data):
                with mock.patch("mixly.scan.known_items", return_value=[]), mock.patch("mixly.scan.store_items", return_value=[]):
                    with mock.patch("mixly.scan.cache_items", return_value=[]):
                        return scan(Journal(self.path("home")), tools, False, None, False, True)

    def test_small_data_folders_are_hidden(self):
        self.write("small/a.bin", "x")
        self.write("big/a.bin", "x" * 200)
        data = [Tool("data:small", "small data", self.path("small")), Tool("data:big", "big data", self.path("big"))]
        with mock.patch("mixly.scan.appdata.MINIMUM", 100):
            found = self.run_scan((), data)
        self.assertEqual([(item.id, item.category) for item in found], [("data:big", DATA)])

    def test_a_parent_of_a_known_tool_is_hidden(self):
        self.write("pip/Cache/a.bin", "x" * 200)
        tools = (Tool("pip-cache", "pip cache", self.path("pip", "Cache")),)
        with mock.patch("mixly.scan.appdata.MINIMUM", 1):
            found = self.run_scan(tools, [Tool("data:pip", "pip data", self.path("pip"))])
        self.assertEqual([item.id for item in found], ["pip-cache"])
