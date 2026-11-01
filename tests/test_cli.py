import contextlib
import io
import os
from unittest import mock

from mixly import cli
from mixly.catalog import Tool
from mixly.journal import Journal
from mixly.links import is_junction
from mixly.scan import scan
from tests.helpers import MemoryEnv, TempCase


class ScanTests(TempCase):
    def test_finds_only_what_exists(self):
        self.write("tool/a.txt", "abc")
        tools = (Tool("a", "A", self.path("tool")), Tool("b", "B", self.path("nope")))
        found = scan(Journal(self.path("home")), tools, include_wsl=False)
        self.assertEqual([(item.id, item.size, item.status) for item in found], [("a", 3, "ready")])
