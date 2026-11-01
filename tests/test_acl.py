import os
import subprocess
from unittest import mock

from mixly.acl import copy_root_permissions, lock_chain, read_dacl, standalone
from mixly.copier import copy_tree
from tests.helpers import TempCase

USERS = "S-1-5-32-545"


def lock_down(path):
    subprocess.run(
        ["icacls", path, "/inheritance:r", "/grant:r", f"*{USERS}:(OI)(CI)RX", "*S-1-5-18:(OI)(CI)F", "*S-1-5-32-544:(OI)(CI)F", f"{os.environ['USERNAME']}:(OI)(CI)F"],
        check=True,
        capture_output=True,
    )


class AclTests(TempCase):
    def test_standalone_removes_inherited_flags(self):
        sddl = "D:AI(A;OICIID;FA;;;SY)(A;ID;0x1200a9;;;BU)(A;OICI;FA;;;BA)"
        self.assertEqual(standalone(sddl), "D:PAI(A;OICI;FA;;;SY)(A;;0x1200a9;;;BU)(A;OICI;FA;;;BA)")

    def test_standalone_leaves_an_acl_without_entries_alone(self):
        self.assertIsNone(standalone("D:NO_ACCESS_CONTROL"))

    def test_copy_keeps_the_root_permissions(self):
        os.makedirs(self.path("src"))
        os.makedirs(self.path("dst"))
        lock_down(self.path("src"))
        copy_root_permissions(self.path("src"), self.path("dst"))
        self.assertEqual(standalone(read_dacl(self.path("dst"))), standalone(read_dacl(self.path("src"))))
        self.assertTrue(read_dacl(self.path("dst")).startswith("D:P"))

    def test_lock_chain_stops_at_the_top(self):
        with mock.patch("mixly.acl.write_dacl") as write:
            lock_chain(self.path("dest", "Mixly"), self.path("dest", "Mixly", "C", "Users"))
        locked = [call.args[0].lower() for call in write.call_args_list]
        self.assertEqual(locked, [self.path("dest", "Mixly", "C", "Users").lower(), self.path("dest", "Mixly", "C").lower(), self.path("dest", "Mixly").lower()])

    def test_lock_chain_refuses_anything_outside_the_top(self):
        with mock.patch("mixly.acl.write_dacl") as write:
            with self.assertRaises(ValueError):
                lock_chain(self.path("dest", "Mixly"), self.path("dest", "Epic Games"))
        write.assert_not_called()

    def test_lock_chain_refuses_a_whole_drive(self):
        with mock.patch("mixly.acl.write_dacl") as write:
            with self.assertRaises(ValueError):
                lock_chain("D:\\", "D:\\Games")
        write.assert_not_called()

    def test_copied_files_inherit_the_permissions(self):
        self.write("src/inner/a.txt")
        lock_down(self.path("src"))
        copy_tree(self.path("src"), self.path("dst"))
        rights = read_dacl(self.path("dst", "inner", "a.txt"))
        self.assertIn(";0x1200a9;;;BU)", rights)
        self.assertNotIn(";FA;;;AU)", rights)
        with open(self.path("dst", "inner", "a.txt"), "a", encoding="utf-8") as handle:
            handle.write("still writable by the owner")
