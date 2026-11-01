import json
import msvcrt
import os
import uuid
from contextlib import contextmanager


class Busy(Exception):
    pass


def home():
    override = os.environ.get("MIXLY_HOME")
    if override:
        return override
    return os.path.join(os.environ["LOCALAPPDATA"], "Mixly")


def new_id():
    return uuid.uuid4().hex[:8]


class Journal:
    def __init__(self, folder=None):
        self.folder = folder or home()
        os.makedirs(self.folder, exist_ok=True)
        self.path = os.path.join(self.folder, "journal.json")

    def records(self):
        try:
            with open(self.path, encoding="utf-8") as handle:
                return json.load(handle)["records"]
        except FileNotFoundError:
            return []

    def get(self, record_id):
        for record in self.records():
            if record["id"] == record_id:
                return record
        raise KeyError(record_id)

    def put(self, record):
        records = [item for item in self.records() if item["id"] != record["id"]]
        records.append(record)
        self._write(records)

    def remove(self, record_id):
        self._write([item for item in self.records() if item["id"] != record_id])

    def _write(self, records):
        temporary = self.path + ".tmp"
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump({"records": records}, handle, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, self.path)
