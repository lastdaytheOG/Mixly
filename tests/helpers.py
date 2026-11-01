import os
import shutil
import tempfile
import unittest


class MemoryEnv:
    def __init__(self, values=None):
        self.values = dict(values or {})
        self.broadcasts = 0

    def items(self):
        return dict(self.values)

    def get(self, name):
        return self.values.get(name)

    def set(self, name, value, kind=1):
        self.values[name] = (value, kind)

    def delete(self, name):
        del self.values[name]

    def broadcast(self):
        self.broadcasts += 1


class TempCase(unittest.TestCase):
    def setUp(self):
        self.base = os.path.realpath(tempfile.mkdtemp(prefix="mixly-test-"))
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        from mixly.links import remove_tree

        remove_tree(self.base)
        shutil.rmtree(self.base, ignore_errors=True)

    def path(self, *parts):
        return os.path.join(self.base, *parts)

    def write(self, relative, content="data"):
        path = self.path(relative)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(content)
        return path
