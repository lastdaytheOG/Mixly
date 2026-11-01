import unittest

from mixly.services import Service, image_path, in_folder, list_services


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
