import ctypes
import os
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import actions, elevation, planner, spacefinder, volumes
from .catalog import CATALOG
from .copier import Cancelled
from .environment import RegistryEnv
from .journal import Journal
from .scan import APPS, CACHES, CAN_CLEAR, DATA, DEVELOPER, GAMES, LARGE, PAUSED, PERSONAL, STAYS, STORE, Found, scan

CHECKED = "☑"
UNCHECKED = "☐"
EVERYTHING = "Everything"
FILTERS = (DEVELOPER, GAMES, APPS, DATA, PERSONAL, STORE, CACHES, LARGE, EVERYTHING)
MOVABLE = ("ready", PAUSED)
UNDOABLE = ("moved", "finished", PAUSED)
TICKABLE = ("ready", PAUSED, "moved", "finished", CAN_CLEAR)


class App(ttk.Frame):
    def __init__(self, master, journal=None, store=None, tools=CATALOG, include_wsl=True, include_installed=True):
        super().__init__(master, padding=14)
        self.master = master
        self.journal = journal or Journal()
        self.store = store or RegistryEnv()
        self.tools = tools
        self.include_wsl = include_wsl
        self.include_installed = include_installed
        self.events = queue.Queue()
        self.cancel = threading.Event()
        self.working = False
        self.rows = {}
        self.checked = set()
        self.large = []
        self._build()
        self.poll = self.after(100, self._drain)
        self.recover_and_scan()

    def destroy(self):
        self.after_cancel(self.poll)
        super().destroy()

    def _build(self):
        self.master.title("Mixly")
        self.master.geometry("1080x680")
        self.master.minsize(900, 520)
        self.pack(fill="both", expand=True)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        ttk.Label(self, text="Free up space on your system drive", font=("Segoe UI", 15, "bold")).grid(row=0, column=0, sticky="w")

        bar = ttk.Frame(self)
        bar.grid(row=1, column=0, sticky="ew", pady=(10, 8))
        ttk.Label(bar, text="Move to").pack(side="left")
        self.drive = ttk.Combobox(bar, state="readonly", width=30)
        self.drive.pack(side="left", padx=(6, 12))
        ttk.Label(bar, text="Show").pack(side="left")
        self.show = ttk.Combobox(bar, state="readonly", width=18, values=FILTERS)
        self.show.current(0)
        self.show.pack(side="left", padx=(6, 12))
        self.show.bind("<<ComboboxSelected>>", lambda event: self._refresh_rows())
        self.scan_button = ttk.Button(bar, text="Scan again", command=self.start_scan)
        self.scan_button.pack(side="left")
        self.space_button = ttk.Button(bar, text="Find large folders", command=self.start_space)
        self.space_button.pack(side="left", padx=6)
        self.add_button = ttk.Button(bar, text="Add folder", command=self.add_folder)
        self.add_button.pack(side="left")
        self.total = ttk.Label(bar, text="")
        self.total.pack(side="right")

        table = ttk.Frame(self)
        table.grid(row=2, column=0, sticky="nsew")
        table.columnconfigure(0, weight=1)
        table.rowconfigure(0, weight=1)
        columns = ("pick", "name", "size", "status", "path")
        self.tree = ttk.Treeview(table, columns=columns, show="headings", selectmode="browse")
        for column, title, width, anchor, stretch in (
            ("pick", "", 34, "center", False),
            ("name", "Name", 230, "w", False),
            ("size", "Size", 84, "e", False),
            ("status", "Status", 110, "w", False),
            ("path", "Location", 520, "w", True),
        ):
            self.tree.heading(column, text=title)
            self.tree.column(column, width=width, anchor=anchor, stretch=stretch)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.bind("<Button-1>", self._on_click)

        actions_bar = ttk.Frame(self)
        actions_bar.grid(row=3, column=0, sticky="ew", pady=10)
        self.move_all_button = ttk.Button(actions_bar, text="Move everything shown", command=self.start_move_everything)
        self.move_all_button.pack(side="left")
        self.move_button = ttk.Button(actions_bar, text="Move selected", command=self.start_move)
        self.move_button.pack(side="left", padx=6)
        self.undo_button = ttk.Button(actions_bar, text="Undo selected", command=self.start_undo)
        self.undo_button.pack(side="left")
        self.finish_button = ttk.Button(actions_bar, text="Delete old copies", command=self.start_finish)
        self.finish_button.pack(side="left", padx=6)
        self.clear_button = ttk.Button(actions_bar, text="Clear selected caches", command=self.start_clear)
        self.clear_button.pack(side="left")
        self.remove_links = tk.BooleanVar(value=False)
        ttk.Checkbutton(actions_bar, text="Also remove links that aren't needed", variable=self.remove_links).pack(side="left", padx=8)
        self.stop_button = ttk.Button(actions_bar, text="Stop", command=self.cancel.set, state="disabled")
        self.stop_button.pack(side="right")

        self.progress = ttk.Progressbar(self, maximum=100)
        self.progress.grid(row=4, column=0, sticky="ew")
        self.log = tk.Text(self, height=7, wrap="word", state="disabled", relief="flat", font=("Segoe UI", 9))
        self.log.grid(row=5, column=0, sticky="ew", pady=(8, 0))
        self._load_drives()

    def _load_drives(self):
        self.drives = volumes.list_drives()
        system = os.environ.get("SystemDrive", "C:").upper()
        self.drive["values"] = [
            f"{drive.root}  {drive.label or 'Local Disk'}  ({volumes.format_size(drive.free)} free)" for drive in self.drives
        ]
        for index, drive in enumerate(self.drives):
            if f"{drive.letter}:" != system:
                self.drive.current(index)
                return
        if self.drives:
            self.drive.current(0)

    def selected_root(self):
        index = self.drive.current()
        return self.drives[index].root if index >= 0 else None

    def write(self, message):
        self.log.configure(state="normal")
        self.log.insert("end", message + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _on_click(self, event):
        row = self.tree.identify_row(event.y)
        if not row or self.tree.identify_column(event.x) != "#1":
            return
        self.toggle(row)

    def toggle(self, row):
        found = self.rows[row]
        if found.status == STAYS:
            self.write(f"{found.name} stays put: {found.reason}.")
            return
        if found.status not in TICKABLE:
            return
        if row in self.checked:
            self.checked.remove(row)
        else:
            self.checked.add(row)
            if found.note:
                self.write(f"{found.name}: {found.note}.")
        if self.tree.exists(row):
            self.tree.set(row, "pick", CHECKED if row in self.checked else UNCHECKED)

    def _visible(self, found):
        return self.show.get() == EVERYTHING or found.category == self.show.get()

    def _values(self, found):
        pick = CHECKED if found.id in self.checked else UNCHECKED
        return (pick, found.name, volumes.format_size(found.size) if found.size else "", found.status, found.source)

    def _update_total(self):
        ready = sum(item.size for item in self.rows.values() if item.status in MOVABLE and self._visible(item))
        clearable = sum(item.size for item in self.rows.values() if item.status == CAN_CLEAR and self._visible(item))
        text = f"{volumes.format_size(ready)} can be moved"
        if clearable:
            text = f"{volumes.format_size(clearable)} can be cleared"
        self.total.configure(text=text)

    def _refresh_rows(self):
        self.tree.delete(*self.tree.get_children())
        for found in self.rows.values():
            if self._visible(found):
                self.tree.insert("", "end", iid=found.id, values=self._values(found))
        self._update_total()

    def _show_found(self, found):
        self.rows[found.id] = found
        if self._visible(found):
            if self.tree.exists(found.id):
                self.tree.item(found.id, values=self._values(found))
            else:
                self.tree.insert("", "end", iid=found.id, values=self._values(found))
        self._update_total()

    def _set_working(self, working):
        self.working = working
        state = "disabled" if working else "normal"
        for button in (
            self.scan_button,
            self.space_button,
            self.add_button,
            self.move_all_button,
            self.move_button,
            self.undo_button,
            self.finish_button,
            self.clear_button,
        ):
            button.configure(state=state)
        self.stop_button.configure(state="normal" if working else "disabled")
        if not working:
            self.progress["value"] = 0

    def _run(self, work):
        if self.working:
            return
        self.cancel.clear()
        self._set_working(True)

        def body():
            try:
                with self.journal.lock():
                    work()
            except Cancelled:
                self.events.put(("log", "Stopped."))
            except actions.ERRORS as error:
                self.events.put(("log", str(error)))
            except Exception as error:
                self.events.put(("log", f"Something went wrong: {error}"))
            self.events.put(("done", None))

        threading.Thread(target=body, daemon=True).start()

    def _drain(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "found":
                    self._show_found(value)
                elif kind == "log":
                    self.write(value)
                elif kind == "progress":
                    self.progress["value"] = value
                elif kind == "show":
                    self.show.set(value)
                    self._refresh_rows()
                elif kind == "reset":
                    self.tree.delete(*self.tree.get_children())
                    self.rows.clear()
                    self.checked.clear()
                elif kind == "done":
                    self._set_working(False)
        except queue.Empty:
            pass
        self.poll = self.after(100, self._drain)

    def _report_progress(self, done, total):
        self.events.put(("progress", done * 100 / total))

    def _scan_work(self):
        self.events.put(("reset", None))
        found = scan(
            self.journal,
            self.tools,
            self.include_wsl,
            lambda item: self.events.put(("found", item)),
            self.include_installed,
        )
        records = self.journal.records()
        for record in records:
            if not any(self._matches(item, record) for item in found):
                category = record.get("category", DEVELOPER)
                status = PAUSED if record["state"] == PAUSED else "moved"
                self.events.put(("found", Found(record["source"], record["name"], record["source"], 0, status, category=category)))
        states = {record["source"].lower(): record["state"] for record in records}
        for item in self.large:
            state = states.get(item.source.lower())
            if state:
                item.status = PAUSED if state == PAUSED else "moved"
            elif item.status in ("moved", PAUSED):
                item.status = "ready"
            if not any(item.source.lower() == other.source.lower() for other in found):
                self.events.put(("found", item))

    @staticmethod
    def _matches(item, record):
        if record.get("distro") and item.distro == record["distro"]:
            return True
        if record.get("known") and item.known == record["known"]:
            return True
        if record.get("package") and item.package == record["package"]:
            return True
        return item.source.lower() == record["source"].lower() and not item.status.startswith("already")

    def start_scan(self):
        self._run(self._scan_work)

    def recover_and_scan(self):
        def work():
            for message in actions.recover(self.journal, self.store):
                self.events.put(("log", message))
            self._scan_work()

        self._run(work)

    def start_space(self):
        root = f"{os.environ.get('SystemDrive', 'C:')}\\"
        self.space_root = getattr(self, "space_root", root)

        def work():
            self.events.put(("log", f"Reading {self.space_root}, which can take a few minutes..."))
            self.events.put(("show", LARGE))
            self.large = spacefinder.find(self.space_root, self.journal, getattr(self, "space_minimum", spacefinder.GIGABYTE), cancel=self.cancel)
            for item in self.large:
                self.events.put(("found", item))
            self.events.put(("log", f"Found {len(self.large)} large items."))

        self._run(work)

    def add_folder(self):
        path = filedialog.askdirectory(title="Choose a folder to move")
        if path:
            self.add_path(path)

    def add_path(self, path):
        clean = os.path.normpath(path)
        self.show.set(EVERYTHING)
        self._refresh_rows()
        self._show_found(Found(clean, os.path.basename(clean), clean, 0, "ready"))
        self.toggle(clean)

    def _chosen(self, *statuses):
        return [self.rows[row] for row in self.checked if self.rows[row].status in statuses and self._visible(self.rows[row])]

    def _record_for(self, found):
        for record in self.journal.records():
            if self._matches(found, record):
                return record
        return None

    def start_move_everything(self, ask=True):
        ready = [found for found in self.rows.values() if found.status in MOVABLE and self._visible(found)]
        if not ready:
            self.write("There's nothing ready to move.")
            return
        root = self.selected_root()
        if root is None:
            self.write("Choose a drive to move to.")
            return
        chosen, left = planner.fit(ready, volumes.free_bytes(volumes.drive_of(root)))
        if not chosen:
            self.write(f"None of this fits on {root}.")
            return
        size = volumes.format_size(sum(found.size for found in chosen))
        message = f"Move {len(chosen)} items ({size}) to {root}?\n\nClose them first. Anything that's open stays where it is."
        if left:
            names = ", ".join(found.name for found in left[:5])
            more = f" and {len(left) - 5} more" if len(left) > 5 else ""
            caches_size = sum(found.size for found in self.rows.values() if found.status == CAN_CLEAR)
            message += f"\n\nThese won't fit and stay put: {names}{more}."
            if caches_size:
                message += f"\nClearing caches would also free {volumes.format_size(caches_size)} on your system drive."
        if ask and not messagebox.askyesno("Move everything", message):
            return
        for found in left:
            self.write(f"{found.name} ({volumes.format_size(found.size)}) doesn't fit on {root}, so it stays.")
        for row in list(self.checked):
            if self.rows[row] in left:
                self.toggle(row)
        for found in chosen:
            if found.id not in self.checked:
                self.toggle(found.id)
        self.start_move()

    def start_move(self):
        chosen = self._chosen(*MOVABLE)
        root = self.selected_root()
        if not chosen:
            self.write("Tick at least one item that's ready to move.")
            return
        if root is None:
            self.write("Choose a drive to move to.")
            return

        def work():
            for found in chosen:
                if self.cancel.is_set():
                    break
                self.events.put(("log", f"Moving {found.name}..."))
                self.events.put(("progress", 0))
                try:
                    record = actions.move_found(found, root, self.journal, self.store, self._report_progress, self.cancel)
                    self.events.put(("log", f"{found.name} moved to {record['target']}."))
                    if record.get("note"):
                        self.events.put(("log", record["note"]))
                except Cancelled:
                    self.events.put(("log", f"{found.name}: paused. Move it again to continue, or undo it to discard the copy."))
                except actions.ERRORS as error:
                    self.events.put(("log", f"{found.name} wasn't moved: {error}"))
            self._scan_work()

        self._run(work)

    def start_undo(self):
        chosen = self._chosen(*UNDOABLE)
        if not chosen:
            self.write("Tick at least one moved item to undo.")
            return

        def work():
            for found in chosen:
                record = self._record_for(found)
                if record is None:
                    continue
                self.events.put(("log", f"Moving {found.name} back..."))
                try:
                    message = actions.undo_record(record, self.journal, self.store, self._report_progress, self.cancel)
                    self.events.put(("log", message))
                except Cancelled:
                    self.events.put(("log", f"{found.name}: stopped, so it stays moved."))
                except actions.ERRORS as error:
                    self.events.put(("log", f"{found.name} wasn't moved back: {error}"))
            self._scan_work()

        self._run(work)

    def start_finish(self, ask=True):
        records = [record for record in self.journal.records() if record["state"] == "moved"]
        if not records:
            self.write("There are no old copies to delete.")
            return
        if ask and not messagebox.askyesno(
            "Delete old copies",
            f"Check that everything still works first. This deletes {len(records)} old copies. Undo will still work.",
        ):
            return
        remove_links = self.remove_links.get()

        def work():
            for record in records:
                try:
                    done = actions.finish_record(record, self.journal, remove_links)
                    note = "the link stays" if done["pointer"] else "nothing is left behind"
                    self.events.put(("log", f"Deleted the old copy of {record['name']}, and {note}."))
                except actions.ERRORS as error:
                    self.events.put(("log", f"{record['name']}: {error}"))
            self._scan_work()

        self._run(work)

    def start_clear(self, ask=True):
        chosen = self._chosen(CAN_CLEAR)
        if not chosen:
            self.write("Choose Caches under Show, then tick what to clear.")
            return
        size = volumes.format_size(sum(found.size for found in chosen))
        if ask and not messagebox.askyesno(
            "Clear caches",
            f"Delete {size} from {len(chosen)} caches?\n\nThis can't be undone, but your tools download or rebuild them when needed.",
        ):
            return

        def work():
            for found in chosen:
                try:
                    self.events.put(("log", actions.clear_cache(found)))
                except actions.ERRORS as error:
                    self.events.put(("log", f"{found.name}: {error}"))
            self._scan_work()

        self._run(work)


def main():
    admin = elevation.is_admin()
    if not admin and elevation.relaunch():
        return 0
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except OSError:
        pass
    root = tk.Tk()
    style = ttk.Style(root)
    if "vista" in style.theme_names():
        style.theme_use("vista")
    app = App(root)
    if not admin:
        app.write("Running without administrator rights, so anything in Program Files can't be moved.")
    root.mainloop()
    return 0
