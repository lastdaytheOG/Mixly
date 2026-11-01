import json
import os
import threading

from .journal import home


class SizeCache:
    def __init__(self, folder=None):
        self.path = os.path.join(folder or home(), "sizes.json")
        self.lock = threading.Lock()
        self.values = {}
        try:
            with open(self.path, encoding="utf-8") as handle:
                self.values = json.load(handle)
        except (OSError, ValueError):
            self.values = {}

    def get(self, path):
        with self.lock:
            return self.values.get(path.lower())

    def put(self, path, size, driver=""):
        with self.lock:
            self.values[path.lower()] = [size, driver]

    def save(self):
        with self.lock:
            data = dict(self.values)
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        temporary = f"{self.path}.{threading.get_ident()}.tmp"
        try:
            with open(temporary, "w", encoding="utf-8") as handle:
                json.dump(data, handle)
            os.replace(temporary, self.path)
        except OSError:
            try:
                os.remove(temporary)
            except OSError:
                pass
