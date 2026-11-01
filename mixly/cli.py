import argparse
import os
import sys

from . import __version__, actions, planner, spacefinder, volumes
from .catalog import by_id
from .copier import Cancelled
from .environment import RegistryEnv
from .journal import Journal
from .scan import APPS, CACHES, CAN_CLEAR, DATA, DEVELOPER, FILES, GAMES, PERSONAL, STORE, Found, scan
from .volumes import format_size, list_drives

CATEGORIES = {
    "tools": DEVELOPER,
    "games": GAMES,
    "apps": APPS,
    "data": DATA,
    "personal": PERSONAL,
    "store": STORE,
    "caches": CACHES,
}
CHOICES = (*CATEGORIES, "all")


def _print_found(items):
    for item in items:
        extra = item.reason or item.note
        note = f"  ({extra})" if extra else ""
        print(f"{item.id:<22}{format_size(item.size):>12}  {item.status:<18}{item.source}{note}")


def _in_category(item, category):
    return category == "all" or item.category == CATEGORIES[category]


def _command_scan(arguments, journal, store):
    items = [item for item in scan(journal) if _in_category(item, arguments.category)]
    _print_found(items)
    total = sum(item.size for item in items if item.status == "ready")
    print(f"\n{format_size(total)} can be moved")
    return 0


def _command_space(arguments, journal, store):
    root = f"{arguments.drive.rstrip(':')}:\\" if arguments.drive and len(arguments.drive) <= 2 else arguments.drive or f"{os.environ.get('SystemDrive', 'C:')}\\"
    minimum = int(arguments.min_gb * spacefinder.GIGABYTE)
    print(f"Reading {root}, which can take a few minutes...")
    _print_found(spacefinder.find(root, journal, minimum))
    return 0


def _command_drives(arguments, journal, store):
    for drive in list_drives():
        print(f"{drive.root:<5}{drive.filesystem:<7}{format_size(drive.free):>10} free of {format_size(drive.total):<10}{drive.label}")
    return 0


def _selection(arguments, journal):
    available = {item.id: item for item in scan(journal)} if arguments.all or arguments.ids else {}
    chosen = []
    if arguments.all:
        destination = volumes.drive_of(arguments.to)
        ready = [
            item
            for item in available.values()
            if item.status in ("ready", "paused") and _in_category(item, arguments.category) and volumes.drive_of(item.source) != destination
        ]
        free = volumes.free_bytes(destination)
        chosen, left = planner.fit(ready, free)
        for item in left:
            print(f"{item.name} ({format_size(item.size)}) doesn't fit on {arguments.to}, so it stays")
    for name in arguments.ids:
        if name not in available:
            raise SystemExit(f"{name} wasn't found. Run: mixly scan")
        chosen.append(available[name])
    for path in arguments.path:
        chosen.append(Found(path, path, path, 0, "ready"))
    return chosen


class _Progress:
    def __init__(self):
        self.last = -1

    def __call__(self, done, total):
        percent = done * 100 // total
        if percent != self.last:
            self.last = percent
            print(f"\r  {percent:>3}%", end="", flush=True)


def _command_move(arguments, journal, store):
    chosen = _selection(arguments, journal)
    if not chosen:
        print("Nothing to move")
        return 0
    if not arguments.yes:
        print(f"This moves {len(chosen)} item(s) to {arguments.to}:")
        _print_found(chosen)
        if input("Continue? [y/N] ").strip().lower() != "y":
            return 1
    failures = 0
    for item in chosen:
        print(item.name)
        try:
            record = actions.move_found(item, arguments.to, journal, store, _Progress())
            print(f"\r  moved to {record['target']} ({record['id']})")
            if record.get("note"):
                print(f"  {record['note']}")
        except (*actions.ERRORS, Cancelled) as error:
            failures += 1
            print(f"\r  not moved: {error}")
    return 1 if failures else 0


def _command_status(arguments, journal, store):
    records = journal.records()
    if not records:
        print("Nothing has been moved")
    for record in records:
        print(f"{record['id']}  {record['state']:<10}{format_size(record['bytes']):>10}  {record['name']}  ->  {record['target']}")
    return 0


def _command_undo(arguments, journal, store):
    print("\r" + actions.undo_record(journal.get(arguments.id), journal, store, _Progress()))
    return 0


def _command_finish(arguments, journal, store):
    records = [journal.get(arguments.id)] if arguments.id else [
        record for record in journal.records() if record["state"] == "moved"
    ]
    if not arguments.yes:
        print(f"This deletes the old copies of {len(records)} item(s). Undo will still work.")
        if input("Continue? [y/N] ").strip().lower() != "y":
            return 1
    failures = 0
    for record in records:
        try:
            done = actions.finish_record(record, journal, arguments.remove_links)
            note = "link kept" if done["pointer"] else "nothing left behind"
            print(f"{done['name']}: old copy deleted, {note}")
        except actions.ERRORS as error:
            failures += 1
            print(f"{record['name']}: {error}")
    return 1 if failures else 0


def _command_clean(arguments, journal, store):
    available = {item.id[len("cache:"):]: item for item in scan(journal, (), False, None, False, True) if item.status == CAN_CLEAR}
    chosen = list(available.values()) if arguments.all else [available[name] for name in arguments.ids if name in available]
    if not chosen:
        print("Nothing to clear")
        return 0
    if not arguments.yes:
        print(f"This deletes {format_size(sum(item.size for item in chosen))}. It downloads or rebuilds when next needed:")
        _print_found(chosen)
        if input("Continue? [y/N] ").strip().lower() != "y":
            return 1
    failures = 0
    for item in chosen:
        try:
            print(actions.clear_cache(item))
        except actions.ERRORS as error:
            failures += 1
            print(f"{item.name}: {error}")
    return 1 if failures else 0


def _command_move_file(arguments, journal, store):
    failures = 0
    for path in arguments.paths:
        found = Found(path, os.path.basename(path), path, 0, "ready", is_item=True, category=FILES)
        try:
            record = actions.move_found(found, arguments.to, journal, store, _Progress())
            print(f"\r{record['name']} moved to {record['target']} ({record['id']})")
        except (*actions.ERRORS, Cancelled) as error:
            failures += 1
            print(f"\r{path}: {error}")
    return 1 if failures else 0


def _command_delete(arguments, journal, store):
    where = "permanently delete" if arguments.permanently else "send to the Recycle Bin"
    if not arguments.yes:
        print(f"This will {where}:")
        print("\n".join(f"  {path}" for path in arguments.paths))
        if input("Continue? [y/N] ").strip().lower() != "y":
            return 1
    failures = 0
    for path in arguments.paths:
        found = Found(path, os.path.basename(path), path, 0, "ready", is_item=True, category=FILES)
        try:
            print(actions.delete_found(found, journal, arguments.permanently))
        except actions.ERRORS as error:
            failures += 1
            print(f"{path}: {error}")
    return 1 if failures else 0


def _command_recover(arguments, journal, store):
    messages = actions.recover(journal, store)
    print("\n".join(messages) if messages else "Nothing needs recovering")
    return 0


def build_parser():
    parser = argparse.ArgumentParser(prog="mixly", description="Move developer tools, games and apps to another drive and keep them working.")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    scan_command = commands.add_parser("scan", help="find what can be moved")
    scan_command.add_argument("--category", choices=CHOICES, default="all")
    scan_command.set_defaults(run=_command_scan)
    space = commands.add_parser("space", help="show what's filling the system drive")
    space.add_argument("--min-gb", type=float, default=1.0)
    space.add_argument("--drive")
    space.set_defaults(run=_command_space)
    move_file = commands.add_parser("move-file", help="move files or folders, leaving nothing behind")
    move_file.add_argument("paths", nargs="+")
    move_file.add_argument("--to", required=True)
    move_file.set_defaults(run=_command_move_file)
    delete = commands.add_parser("delete", help="send files or folders to the Recycle Bin")
    delete.add_argument("paths", nargs="+")
    delete.add_argument("--permanently", action="store_true")
    delete.add_argument("--yes", action="store_true")
    delete.set_defaults(run=_command_delete)
    commands.add_parser("drives", help="list internal drives").set_defaults(run=_command_drives)
    move = commands.add_parser("move", help="move tools, games, apps or folders to another drive")
    move.add_argument("ids", nargs="*")
    move.add_argument("--to", required=True)
    move.add_argument("--all", action="store_true")
    move.add_argument("--category", choices=CHOICES, default="tools")
    move.add_argument("--path", action="append", default=[])
    move.add_argument("--yes", action="store_true")
    move.set_defaults(run=_command_move)
    commands.add_parser("status", help="show what has been moved").set_defaults(run=_command_status)
    undo = commands.add_parser("undo", help="move something back")
    undo.add_argument("id")
    undo.set_defaults(run=_command_undo)
    finish = commands.add_parser("finish", help="delete the old copies")
    finish.add_argument("id", nargs="?")
    finish.add_argument("--remove-links", action="store_true")
    finish.add_argument("--yes", action="store_true")
    finish.set_defaults(run=_command_finish)
    clean = commands.add_parser("clean", help="clear caches that can be downloaded again")
    clean.add_argument("ids", nargs="*")
    clean.add_argument("--all", action="store_true")
    clean.add_argument("--yes", action="store_true")
    clean.set_defaults(run=_command_clean)
    commands.add_parser("recover", help="clean up after an interrupted move").set_defaults(run=_command_recover)
    return parser


def main(argv=None):
    arguments = build_parser().parse_args(argv)
    journal = Journal()
    store = RegistryEnv()
    try:
        with journal.lock():
            if arguments.run is not _command_recover:
                for message in actions.recover(journal, store):
                    print(message)
            return arguments.run(arguments, journal, store)
    except actions.ERRORS as error:
        print(error, file=sys.stderr)
        return 1
