import argparse
import sys

from . import __version__, actions, mover, wsl
from .catalog import by_id
from .copier import Cancelled, CopyError
from .environment import RegistryEnv
from .journal import Busy, Journal
from .scan import APPS, DEVELOPER, GAMES, Found, scan
from .volumes import format_size, list_drives


CATEGORIES = {"tools": DEVELOPER, "games": GAMES, "apps": APPS}


def _print_found(items):
    for item in items:
        note = f"  ({item.reason})" if item.reason else ""
        print(f"{item.id:<22}{format_size(item.size):>12}  {item.status:<18}{item.source}{note}")


def _in_category(item, category):
    return category == "all" or item.category == CATEGORIES[category]


def _command_scan(arguments, journal, store):
    items = [item for item in scan(journal) if _in_category(item, arguments.category)]
    _print_found(items)
    total = sum(item.size for item in items if item.status == "ready")
    print(f"\n{format_size(total)} can be moved")
    return 0


def _command_drives(arguments, journal, store):
    for drive in list_drives():
        print(f"{drive.root:<5}{drive.filesystem:<7}{format_size(drive.free):>10} free of {format_size(drive.total):<10}{drive.label}")
    return 0


def _selection(arguments, journal):
    available = {item.id: item for item in scan(journal)} if arguments.all or arguments.ids else {}
    chosen = []
    if arguments.all:
        chosen = [item for item in available.values() if item.status == "ready" and _in_category(item, arguments.category)]
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
        except (mover.MoveError, wsl.WslError, CopyError, Cancelled, OSError) as error:
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
        except (mover.MoveError, OSError) as error:
            failures += 1
            print(f"{record['name']}: {error}")
    return 1 if failures else 0


def _command_recover(arguments, journal, store):
    messages = mover.recover(journal, store)
    print("\n".join(messages) if messages else "Nothing needs recovering")
    return 0


def build_parser():
    parser = argparse.ArgumentParser(prog="mixly", description="Move developer tools to another drive and keep them working.")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    scan_command = commands.add_parser("scan", help="find what can be moved")
    scan_command.add_argument("--category", choices=("tools", "games", "apps", "all"), default="all")
    scan_command.set_defaults(run=_command_scan)
    commands.add_parser("drives", help="list internal drives").set_defaults(run=_command_drives)
    move = commands.add_parser("move", help="move tools or folders to another drive")
    move.add_argument("ids", nargs="*")
    move.add_argument("--to", required=True)
    move.add_argument("--all", action="store_true")
    move.add_argument("--category", choices=("tools", "games", "apps", "all"), default="tools")
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
    commands.add_parser("recover", help="clean up after an interrupted move").set_defaults(run=_command_recover)
    return parser


def main(argv=None):
    arguments = build_parser().parse_args(argv)
    journal = Journal()
    store = RegistryEnv()
    try:
        with journal.lock():
            if arguments.run is not _command_recover:
                for message in mover.recover(journal, store):
                    print(message)
            return arguments.run(arguments, journal, store)
    except (Busy, mover.MoveError, wsl.WslError, KeyError, CopyError, OSError) as error:
        print(error, file=sys.stderr)
        return 1
