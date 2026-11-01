import os
import sys
from unittest import mock

from mixly import elevation, gui
from tests.helpers import TempCase


class ElevationTests(TempCase):
    def test_can_replace_a_folder_in_a_writable_place(self):
        os.makedirs(self.path("app"))
        self.assertTrue(elevation.can_replace(self.path("app")))
        self.assertEqual(os.listdir(self.base), ["app"])

    def test_cant_replace_when_the_parent_refuses(self):
        with mock.patch("mixly.elevation.os.mkdir", side_effect=PermissionError):
            self.assertFalse(elevation.can_replace(self.path("app")))

    def test_relaunch_runs_the_module_from_source(self):
        program, parameters, folder = elevation.relaunch_command()
        self.assertEqual((program, parameters), (sys.executable, "-m mixly"))
        self.assertTrue(os.path.isdir(os.path.join(folder, "mixly")))

    def test_relaunch_runs_the_exe_when_frozen(self):
        with mock.patch.object(sys, "frozen", True, create=True):
            self.assertEqual(elevation.relaunch_command(), (sys.executable, "", None))

    def test_the_window_opens_elevated_and_closes_this_copy(self):
        with mock.patch.object(gui.elevation, "is_admin", return_value=False):
            with mock.patch.object(gui.elevation, "relaunch", return_value=True) as relaunch:
                with mock.patch.object(gui.tk, "Tk") as window:
                    self.assertEqual(gui.main(), 0)
        relaunch.assert_called_once()
        window.assert_not_called()
