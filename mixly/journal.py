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
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, "Mixly")


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
                data = json.load(handle)
                return data["records"] if isinstance(data, dict) and isinstance(data.get("records"), list) else []
        except (FileNotFoundError, json.JSONDecodeError, ValueError, OSError, KeyError):
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

    @contextmanager
    def lock(self):
        handle = open(os.path.join(self.folder, "lock"), "a+b")
        try:
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as error:
                raise Busy("Mixly is already moving something") from error
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        finally:
            handle.close()
