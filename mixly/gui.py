import ctypes
import os
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import actions, elevation, mover, volumes, wsl
from .catalog import CATALOG
from .copier import Cancelled, CopyError
from .environment import RegistryEnv
from .journal import Busy, Journal
from .scan import APPS, DEVELOPER, GAMES, STAYS, Found, scan

ERRORS = (mover.MoveError, wsl.WslError, CopyError, OSError, Busy, KeyError)
CHECKED = "☑"
UNCHECKED = "☐"
EVERYTHING = "Everything"


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
        self._build()
        self.poll = self.after(100, self._drain)
        self.recover_and_scan()

    def destroy(self):
        self.after_cancel(self.poll)
        super().destroy()

    def _build(self):
        self.master.title("Mixly")
        self.master.geometry("920x620")
        self.master.minsize(720, 480)
        self.pack(fill="both", expand=True)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        ttk.Label(self, text="Move your tools, games and apps to another drive", font=("Segoe UI", 15, "bold")).grid(row=0, column=0, sticky="w")

        bar = ttk.Frame(self)
        bar.grid(row=1, column=0, sticky="ew", pady=(10, 8))
        ttk.Label(bar, text="Move to").pack(side="left")
        self.drive = ttk.Combobox(bar, state="readonly", width=30)
        self.drive.pack(side="left", padx=(6, 12))
        ttk.Label(bar, text="Show").pack(side="left")
        self.show = ttk.Combobox(bar, state="readonly", width=15, values=(DEVELOPER, GAMES, APPS, EVERYTHING))
        self.show.current(0)
        self.show.pack(side="left", padx=(6, 12))
        self.show.bind("<<ComboboxSelected>>", lambda event: self._refresh_rows())
        self.scan_button = ttk.Button(bar, text="Scan again", command=self.start_scan)
        self.scan_button.pack(side="left")
        self.add_button = ttk.Button(bar, text="Add folder", command=self.add_folder)
        self.add_button.pack(side="left", padx=6)
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
            ("name", "Tool", 200, "w", False),
            ("size", "Size", 84, "e", False),
            ("status", "Status", 110, "w", False),
            ("path", "Location", 420, "w", True),
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
        self.remove_links = tk.BooleanVar(value=False)
        ttk.Checkbutton(actions_bar, text="Also remove links that aren't needed", variable=self.remove_links).pack(side="left")
        self.stop_button = ttk.Button(actions_bar, text="Stop", command=self.cancel.set, state="disabled")
        self.stop_button.pack(side="right")

        self.progress = ttk.Progressbar(self, maximum=100)
        self.progress.grid(row=4, column=0, sticky="ew")
        self.log = tk.Text(self, height=7, wrap="word", state="disabled", relief="flat", font=("Segoe UI", 9))
        self.log.grid(row=5, column=0, sticky="ew", pady=(8, 0))
        self._load_drives()

    def _load_drives(self):
        self.drives = volumes.list_drives()
        system = volumes.drive_of(self.tools[0].source) if self.tools else ""
        choices = []
        for drive in self.drives:
            label = f"{drive.root}  {drive.label or 'Local Disk'}  ({volumes.format_size(drive.free)} free)"
            choices.append(label)
        self.drive["values"] = choices
        for index, drive in enumerate(self.drives):
            if f"{drive.letter}:" != system:
                self.drive.current(index)
                break
        else:
            if choices:
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
        if found.status not in ("ready", "moved", "finished"):
            return
        if row in self.checked:
            self.checked.remove(row)
        else:
            self.checked.add(row)
        if self.tree.exists(row):
            self.tree.set(row, "pick", CHECKED if row in self.checked else UNCHECKED)

    def _visible(self, found):
        return self.show.get() == EVERYTHING or found.category == self.show.get()

    def _values(self, found):
        pick = CHECKED if found.id in self.checked else UNCHECKED
        return (pick, found.name, volumes.format_size(found.size) if found.size else "", found.status, found.source)

    def _update_total(self):
        ready = sum(item.size for item in self.rows.values() if item.status == "ready" and self._visible(item))
        self.total.configure(text=f"{volumes.format_size(ready)} can be moved")

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
        for button in (self.scan_button, self.add_button, self.move_all_button, self.move_button, self.undo_button, self.finish_button):
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
            except ERRORS as error:
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
        for record in self.journal.records():
            if not any(item.source.lower() == record["source"].lower() or item.distro == record.get("distro") for item in found):
                self.events.put(("found", Found(record["source"], record["name"], record["source"], 0, "moved")))

    def start_scan(self):
        self._run(self._scan_work)

    def recover_and_scan(self):
        def work():
            for message in mover.recover(self.journal, self.store):
                self.events.put(("log", message))
            self._scan_work()

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
            if record["source"].lower() == found.source.lower() or (found.distro and record.get("distro") == found.distro):
                return record
        return None

    def start_move_everything(self, ask=True):
        ready = [row for row, found in self.rows.items() if found.status == "ready" and self._visible(found)]
        if not ready:
            self.write("There's nothing ready to move.")
            return
        size = volumes.format_size(sum(self.rows[row].size for row in ready))
        if ask and not messagebox.askyesno(
            "Move everything",
            f"Move {len(ready)} items ({size}) to {self.selected_root()}?\n\nClose your tools first. Anything that's open or doesn't fit stays where it is.",
        ):
            return
        for row in ready:
            if row not in self.checked:
                self.toggle(row)
        self.start_move()

    def start_move(self):
        chosen = self._chosen("ready")
        root = self.selected_root()
        if not chosen:
            self.write("Tick at least one tool that's ready to move.")
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
                except Cancelled:
                    self.events.put(("log", f"{found.name}: stopped, and nothing was changed."))
                except ERRORS as error:
                    self.events.put(("log", f"{found.name} wasn't moved: {error}"))
            self._scan_work()

        self._run(work)

    def start_undo(self):
        chosen = self._chosen("moved", "finished")
        if not chosen:
            self.write("Tick at least one moved tool to undo.")
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
                except ERRORS as error:
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
            f"Check that your tools still work first. This deletes {len(records)} old copies. Undo will still work.",
        ):
            return
        remove_links = self.remove_links.get()

        def work():
            for record in records:
                try:
                    done = actions.finish_record(record, self.journal, remove_links)
                    note = "the link stays" if done["pointer"] else "nothing is left behind"
                    self.events.put(("log", f"Deleted the old copy of {record['name']}, and {note}."))
                except ERRORS as error:
                    self.events.put(("log", f"{record['name']}: {error}"))
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
