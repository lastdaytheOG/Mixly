import unittest
from types import SimpleNamespace

from mixly.services import Service, ServiceError, image_path, in_folder, list_services, start, start_all, stop, stop_all


class FakeControl:
    def __init__(self, states=None, stuck=()):
        self.states = dict(states or {})
        self.stuck = set(stuck)
        self.calls = []

    def __call__(self, arguments):
        self.calls.append(arguments)
        command, name = arguments
        if command == "stop" and name not in self.stuck:
            self.states[name] = 1
        if command == "start" and name not in self.stuck:
            self.states[name] = 4
        return SimpleNamespace(stdout=f"STATE              : {self.states.get(name, 1)}  X\n")


def options(control):
    return {"run": control, "timeout": 0, "wait": lambda seconds: None}


class ControlTests(unittest.TestCase):
    def test_must_stay_for_drivers_and_early_start(self):
        self.assertTrue(Service("A", "x", kind=1).must_stay)
        self.assertTrue(Service("A", "x", kind=2).must_stay)
        self.assertTrue(Service("A", "x", start=0).must_stay)
        self.assertTrue(Service("A", "x", start=1).must_stay)
        self.assertFalse(Service("A", "x", start=2).must_stay)

    def test_stop_returns_whether_it_was_running(self):
        control = FakeControl({"A": 4, "B": 1})
        self.assertTrue(stop("A", **options(control)))
        self.assertFalse(stop("B", **options(control)))
        self.assertNotIn(["stop", "B"], control.calls)

    def test_a_stuck_service_raises(self):
        control = FakeControl({"A": 4}, stuck=["A"])
        with self.assertRaises(ServiceError):
            stop("A", **options(control))
        control = FakeControl({"A": 1}, stuck=["A"])
        with self.assertRaises(ServiceError):
            start("A", **options(control))

    def test_stop_all_only_lists_what_it_stopped(self):
        control = FakeControl({"A": 4, "B": 1})
        self.assertEqual(stop_all(["A", "B"], **options(control)), ["A"])

    def test_stop_all_restarts_the_others_when_one_is_stuck(self):
        control = FakeControl({"A": 4, "B": 4}, stuck=["B"])
        with self.assertRaises(ServiceError):
            stop_all(["A", "B"], **options(control))
        self.assertEqual(control.states["A"], 4)

    def test_start_all(self):
        control = FakeControl({"A": 1})
        start_all(["A"], **options(control))
        self.assertEqual(control.states["A"], 4)


class ImagePathTests(unittest.TestCase):
    def test_quoted_path_with_arguments(self):
        self.assertEqual(image_path(r'"C:\Program Files\App\svc.exe" --run'), r"C:\Program Files\App\svc.exe")

    def test_unquoted_path_with_arguments(self):
        self.assertEqual(image_path(r"C:\App Dir\svc.exe -k x"), r"C:\App Dir\svc.exe")

    def test_driver_path(self):
        self.assertEqual(image_path("\\??\\C:\\App\\drv.sys"), r"C:\App\drv.sys")


class InFolderTests(unittest.TestCase):
    def test_matches_only_inside_the_folder(self):
        listing = [Service("In", r"C:\App\svc.exe"), Service("Out", r"C:\App2\svc.exe")]
        self.assertEqual([service.name for service in in_folder(r"C:\App", listing)], ["In"])

    def test_reads_real_services(self):
        self.assertTrue(list_services())
