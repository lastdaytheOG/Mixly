import os
from types import SimpleNamespace
from unittest import mock

from mixly import wsl
from mixly.journal import Journal
from tests.helpers import TempCase

LISTING = "  NAME      STATE           VERSION\n* Ubuntu    Stopped         2\n  Debian    Stopped         2\n".encode("utf-16-le")
LISTING_RUNNING = "  NAME      STATE           VERSION\n* Ubuntu    Stopped         2\n  Debian    Running         2\n".encode("utf-16-le")


class FakeWsl:
    def __init__(self, base, listing=LISTING, code=0):
        self.listing = listing
        self.code = code
        self.calls = []
        self.locations = {"Ubuntu": base, "Debian": base}

    def run(self, arguments):
        self.calls.append(arguments)
        if arguments[0] == "--list":
            return SimpleNamespace(returncode=0, stdout=self.listing, stderr=b"")
        if arguments[0] == "--shutdown":
            return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")
        if self.code == 0:
            self.locations[arguments[1]] = arguments[3]
        return SimpleNamespace(returncode=self.code, stdout=b"boom", stderr=b"")

    def paths(self):
        return dict(self.locations)


class WslTests(TempCase):
    def setUp(self):
        super().setUp()
        self.journal = Journal(self.path("home"))
        self.fake = FakeWsl(r"Z:\old")
        patcher = mock.patch("mixly.wsl.volumes.drive_of", side_effect=lambda path: path[:2].upper())
        patcher.start()
        self.addCleanup(patcher.stop)
        for name, value in (("free_bytes", 10**12), ("drive_type", 3)):
            patcher = mock.patch(f"mixly.wsl.volumes.{name}", return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def move(self, name="Ubuntu"):
        return wsl.move(name, self.base, self.journal, self.fake.run, self.fake.paths)

    def test_parses_utf16_listing(self):
        names = [distro["name"] for distro in wsl.list_distros(self.fake.run)]
        self.assertEqual(names, ["Ubuntu", "Debian"])

    def test_move_calls_wsl_and_records_it(self):
        record = self.move()
        self.assertEqual(self.fake.locations["Ubuntu"], record["target"])
        self.assertIn(["--manage", "Ubuntu", "--move", record["target"]], self.fake.calls)
        self.assertLess(self.fake.calls.index(["--shutdown"]), self.fake.calls.index(["--manage", "Ubuntu", "--move", record["target"]]))
        self.assertEqual(self.journal.get(record["id"])["source"], r"Z:\old")

    def test_refuses_when_any_distro_is_running(self):
        self.fake.listing = LISTING_RUNNING
        with self.assertRaises(wsl.WslError):
            self.move("Ubuntu")
        self.assertNotIn(["--shutdown"], self.fake.calls)
        self.assertEqual(self.journal.records(), [])

    def test_refuses_docker_distros(self):
        with self.assertRaises(wsl.WslError):
            self.move("docker-desktop")
        self.assertEqual(self.fake.calls, [])

    def test_failure_is_reported_and_not_recorded(self):
        self.fake.code = 1
        with self.assertRaises(wsl.WslError):
            self.move()
        self.assertEqual(self.journal.records(), [])

    def test_success_without_moving_is_caught(self):
        original = self.fake.run

        def lying(arguments):
            result = original(arguments)
            if arguments[0] == "--manage":
                self.fake.locations["Ubuntu"] = r"Z:\old"
            return result

        with self.assertRaises(wsl.WslError):
            wsl.move("Ubuntu", self.base, self.journal, lying, self.fake.paths)
        self.assertEqual(self.journal.records(), [])

    def test_undo_moves_it_back(self):
        record = self.move()
        with mock.patch("mixly.wsl.os.makedirs"):
            wsl.undo(record["id"], self.journal, self.fake.run, self.fake.paths)
        self.assertEqual(self.fake.locations["Ubuntu"], r"Z:\old")
        self.assertEqual(self.journal.records(), [])
        self.assertFalse(os.path.exists(record["target"]))
