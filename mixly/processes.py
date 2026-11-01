import csv
import io
import subprocess

CREATE_NO_WINDOW = 0x08000000


def running_names():
    result = subprocess.run(
        ["tasklist", "/fo", "csv", "/nh"],
        capture_output=True,
        creationflags=CREATE_NO_WINDOW,
    )
    text = result.stdout.decode("oem", errors="replace")
    return {row[0].lower() for row in csv.reader(io.StringIO(text)) if row}


def still_running(wanted, names=None):
    active = running_names() if names is None else names
    return sorted(name for name in wanted if name.lower() in active)
