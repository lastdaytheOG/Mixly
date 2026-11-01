import os
import threading
from unittest import mock

from mixly.copier import Cancelled
from mixly.journal import Journal
from mixly.links import create_junction
from mixly.services import Service
from mixly.spacefinder import Node, find, pick, read_tree
from tests.helpers import TempCase


def fill(path, size):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(b"x" * size)


class ReadTreeTests(TempCase):
    def test_adds_up_sizes_and_keeps_big_children(self):
        fill(self.path("root", "big", "a.bin"), 100)
        fill(self.path("root", "small", "b.bin"), 5)
        tree = read_tree(self.path("root"), 50)
        self.assertEqual(tree.size, 105)
        self.assertEqual([child.path for child in tree.children], [self.path("root", "big")])

    def test_never_counts_through_a_junction(self):
        fill(self.path("outside", "huge.bin"), 1000)
        fill(self.path("root", "a.bin"), 5)
        create_junction(self.path("outside"), self.path("root", "link"))
        self.assertEqual(read_tree(self.path("root"), 50).size, 5)

    def test_notes_big_files(self):
        fill(self.path("root", "pagefile.sys"), 100)
        self.assertEqual(read_tree(self.path("root"), 50).files, [(self.path("root", "pagefile.sys"), 100)])

    def test_stop_cancels_it(self):
        fill(self.path("root", "a.bin"), 5)
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(Cancelled):
            read_tree(self.path("root"), 50, cancel=cancel)


class PickTests(TempCase):
    def test_never_digs_inside_a_movable_folder(self):
        node = Node(self.path("a"), 100, [Node(self.path("a", "lib"), 90)])
        self.assertEqual(pick(node, 10, containers=set()), [(self.path("a"), 100, "")])

    def test_opens_up_a_general_folder(self):
        documents = self.path("Documents")
        node = Node(documents, 100, [Node(os.path.join(documents, "ProjectA"), 50), Node(os.path.join(documents, "ProjectB"), 50)])
        result = pick(node, 10, containers={documents.lower()})
        self.assertEqual([entry[0] for entry in result], [os.path.join(documents, "ProjectA"), os.path.join(documents, "ProjectB")])

    def test_a_general_folder_with_only_small_contents_is_listed_whole(self):
        documents = self.path("Documents")
        self.assertEqual(pick(Node(documents, 100), 10, containers={documents.lower()}), [(documents, 100, "")])

    def test_reports_temp_as_staying(self):
        temporary = os.path.join(os.environ["LOCALAPPDATA"], "Temp")
        result = pick(Node(temporary, 100), 10, containers=set())
        self.assertIn("temporary", result[0][2])

    def test_reports_app_packages_as_staying(self):
        packages = os.path.join(os.environ["LOCALAPPDATA"], "Packages", "Some.App")
        self.assertTrue(pick(Node(packages, 100), 10, containers=set())[0][2])

    def test_goes_through_protected_containers(self):
        users = Node(r"C:\Users", 100, [Node(os.environ["USERPROFILE"], 100, [Node(self.path("a"), 100)])])
        self.assertEqual(pick(users, 10), [(self.path("a"), 100, "")])

    def test_reports_windows_as_staying(self):
        windows = Node(os.environ["windir"], 100, [Node(os.path.join(os.environ["windir"], "System32"), 90)])
        result = pick(windows, 10)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0][0], os.environ["windir"])
        self.assertTrue(result[0][2])


class FindTests(TempCase):
    def setUp(self):
        super().setUp()
        self.journal = Journal(self.path("home"))

    def test_marks_movable_folders_ready(self):
        fill(self.path("root", "a", "one.bin"), 100)
        fill(self.path("root", "b", "two.bin"), 100)
        found = find(self.path("root"), self.journal, 50, listing=[])
        self.assertEqual([(item.source, item.status) for item in found], [(self.path("root"), "ready")])
        self.assertEqual(found[0].category, "Large folders")

    def test_a_folder_with_a_driver_stays(self):
        fill(self.path("root", "a", "one.bin"), 100)
        fill(self.path("root", "b", "two.bin"), 100)
        listing = [Service("Drv", self.path("root", "a", "d.sys"), kind=1)]
        found = find(self.path("root"), self.journal, 50, listing=listing)
        self.assertEqual(found[0].status, "stays put")
        self.assertIn("Drv", found[0].reason)

    def test_moved_folders_show_as_moved(self):
        fill(self.path("root", "a", "one.bin"), 100)
        fill(self.path("root", "b", "two.bin"), 100)
        self.journal.put({"id": "m", "source": self.path("root"), "state": "moved"})
        self.assertEqual(find(self.path("root"), self.journal, 50, listing=[])[0].status, "moved")

    def test_big_system_files_stay(self):
        fill(self.path("root", "hiberfil.sys"), 100)
        found = find(self.path("root"), self.journal, 50, listing=[])
        files = [item for item in found if item.name == "hiberfil.sys"]
        self.assertEqual(files[0].status, "stays put")
