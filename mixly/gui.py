import ctypes
import os
import queue
import threading
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor
from tkinter import filedialog, ttk

from . import actions, browser, elevation, planner, spacefinder, theme, volumes
from .catalog import CATALOG
from .copier import Cancelled
from .environment import RegistryEnv
from .journal import Journal
from .scan import (
    APPS,
    CACHES,
    CAN_CLEAR,
    DATA,
    DEVELOPER,
    FILES,
    GAMES,
    LARGE,
    MOVED,
    PAUSED,
    PERSONAL,
    STAYS,
    STORE,
    WORKERS,
    Found,
    discover,
    settle,
)
from .sizes import SizeCache

CHECKED = "\u2611"
UNCHECKED = "\u2610"
CHOOSE_FOLDER = "Choose a folder\u2026"
MOVABLE = ("ready", PAUSED)
UNDOABLE = ("moved", "finished", PAUSED)
TICKABLE = ("ready", PAUSED, "moved", "finished", CAN_CLEAR)
ICON_CODE = "\ue943"
ICON_GAME = "\ue7fc"
ICON_APPS = "\uecaa"
ICON_DATA = "\ue8b7"
ICON_PERSON = "\ue77b"
ICON_STORE = "\ue719"
ICON_LARGE = "\ue9d2"
ICON_CACHE = "\ue74d"
ICON_FILES = "\ue8a5"
ICON_MOVED = "\ue8ab"
ICON_UP = "\ue74a"
NAVIGATION = (
    ("Free up space", ((DEVELOPER, ICON_CODE), (GAMES, ICON_GAME), (APPS, ICON_APPS), (DATA, ICON_DATA), (PERSONAL, ICON_PERSON), (STORE, ICON_STORE))),
    ("Explore", ((LARGE, ICON_LARGE), (FILES, ICON_FILES), (CACHES, ICON_CACHE))),
    ("History", ((MOVED, ICON_MOVED),)),
)
HINTS = {
    DEVELOPER: "Tools and packages that follow you to the new drive. Old paths keep working.",
    GAMES: "Games from Steam, Epic, GOG and Ubisoft Connect.",
    APPS: "Installed apps. Their settings stay where they are.",
    DATA: "App data and game saves over 100 MB.",
    PERSONAL: "Move a whole folder, or double-click one to move what's inside.",
    STORE: "Windows moves these itself and decides which ones can go.",
    LARGE: "Scan a drive to see what's really using the space.",
    FILES: "Browse any drive. Tick files and folders to move or delete them.",
    CACHES: "Your tools download or rebuild these when they need them.",
    MOVED: "Everything Mixly moved. Undo works at any time.",
}
EMPTY = {
    DEVELOPER: "No developer tools found on this PC.",
    GAMES: "No games found.\nSteam, Epic, GOG and Ubisoft Connect are checked automatically.",
    APPS: "No apps found.",
    DATA: "No app data over 100 MB.",
    PERSONAL: "Your personal folders couldn't be read.",
    STORE: "No Store apps can be moved.\nDrivers and parts of Windows are hidden here.",
    LARGE: "Pick a drive above and click Scan to see what's using its space.",
    FILES: "This folder is empty.",
    CACHES: "No caches to clear.",
    MOVED: "Nothing has been moved yet.\nWhat you move shows up here, ready to undo.",
}


def format_size(found):
    if found.pending and not found.size:
        return "\u2026"
    return volumes.format_size(found.size) if found.size else ""


class Confirm(tk.Toplevel):
    def __init__(self, parent, palette, title, body, choices):
        super().__init__(parent)
        self.result = None
        self.title(title)
        self.transient(parent)
        self.resizable(False, False)
        self.configure(background=palette.surface)
        frame = ttk.Frame(self, padding=20)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text=title, font=(theme.SEMIBOLD, 13)).pack(anchor="w")
        ttk.Label(frame, text=body, wraplength=440, justify="left", style="Muted.TLabel").pack(anchor="w", pady=(8, 18))
        row = ttk.Frame(frame)
        row.pack(fill="x")
        for index, (label, value) in enumerate(reversed(choices)):
            primary = index == len(choices) - 1
            button = ttk.Button(row, text=label, style="Primary.TButton" if primary else "TButton", command=lambda chosen=value: self._pick(chosen))
            button.pack(side="right", padx=(8, 0))
            if primary:
                button.focus_set()
        self.bind("<Escape>", lambda event: self._pick(None))
        theme.dark_title_bar(self, palette.name == "dark")
        self.update_idletasks()
        x = parent.winfo_rootx() + (parent.winfo_width() - self.winfo_width()) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - self.winfo_height()) // 3
        self.geometry(f"+{x}+{y}")
        self.grab_set()

    def _pick(self, value):
        self.result = value
        self.destroy()


class App(ttk.Frame):
    def __init__(self, master, journal=None, store=None, tools=CATALOG, include_wsl=True, include_installed=True, sizes=None):
        super().__init__(master)
        self.master = master
        self.journal = journal or Journal()
        self.store = store or RegistryEnv()
        self.sizes = sizes or SizeCache(self.journal.folder)
        self.tools = tools
        self.include_wsl = include_wsl
        self.include_installed = include_installed
        self.palette = theme.current()
        self.scale = theme.apply(master, self.palette)
        self.events = queue.Queue()
        self.cancel = threading.Event()
        self.working = False
        self.sizing = False
        self.generation = 0
        self.allow_same_drive = False
        self.rows = {}
        self.checked = set()
        self.large = []
        self.drives = []
        self.destination = None
        self.show = tk.StringVar(value=DEVELOPER)
        self.search = tk.StringVar()
        self.folder = None
        self.space_minimum = spacefinder.GIGABYTE
        self.sort_column = "size"
        self.sort_reverse = True
        self.needs_sort = False
        self.nav = {}
        self.nav_totals = {}
        self.drive_rows = []
        self._build()
        self.poll = self.after(40, self._drain)
        self.sort_poll = self.after(400, self._periodic_sort)
        self.select_view(DEVELOPER)
        self.recover_and_scan()

    def px(self, value):
        return round(value * self.scale)

    def destroy(self):
        self.generation += 1
        self.after_cancel(self.poll)
        self.after_cancel(self.sort_poll)
        super().destroy()

    def _build(self):
        self.master.title("Mixly")
        self.master.geometry(f"{self.px(1180)}x{self.px(720)}")
        self.master.minsize(self.px(980), self.px(560))
        self.pack(fill="both", expand=True)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)
        self._build_sidebar()
        main = ttk.Frame(self, padding=(self.px(22), self.px(18), self.px(22), self.px(14)))
        main.grid(row=0, column=1, sticky="nsew")
        main.columnconfigure(0, weight=1)
        main.rowconfigure(3, weight=1)
        self._build_header(main)
        self._build_files_bar(main)
        self._build_table(main)
        self._build_actions(main)
        self._load_drives()

    def _build_sidebar(self):
        palette = self.palette
        side = tk.Frame(self, background=palette.side, width=self.px(244))
        side.grid(row=0, column=0, sticky="ns")
        side.grid_propagate(False)
        side.columnconfigure(0, weight=1)
        side.rowconfigure(1, weight=1)
        tk.Label(side, text="Mixly", background=palette.side, foreground=palette.ink, font=(theme.SEMIBOLD, 15), anchor="w").grid(row=0, column=0, sticky="ew", padx=self.px(18), pady=(self.px(16), self.px(8)))
        menu = tk.Frame(side, background=palette.side)
        menu.grid(row=1, column=0, sticky="new", padx=self.px(8))
        menu.columnconfigure(0, weight=1)
        row = 0
        for heading, items in NAVIGATION:
            tk.Label(menu, text=heading, background=palette.side, foreground=palette.muted, font=(theme.FONT, 9), anchor="w").grid(row=row, column=0, sticky="ew", padx=self.px(10), pady=(self.px(10), self.px(3)))
            row += 1
            for name, icon in items:
                self._nav_item(menu, name, icon).grid(row=row, column=0, sticky="ew")
                row += 1
        self.drive_panel = tk.Frame(side, background=palette.side)
        self.drive_panel.grid(row=2, column=0, sticky="ew", padx=self.px(18), pady=(self.px(8), self.px(16)))
        self.drive_panel.columnconfigure(0, weight=1)

    def _nav_item(self, parent, name, icon):
        palette = self.palette
        item = tk.Frame(parent, background=palette.side, cursor="hand2", takefocus=1, highlightthickness=1, highlightbackground=palette.side, highlightcolor=palette.accent)
        item.columnconfigure(1, weight=1)
        symbol = tk.Label(item, text=icon, font=(theme.ICONS, 11), background=palette.side, foreground=palette.muted, width=2)
        symbol.grid(row=0, column=0, padx=(self.px(6), self.px(4)), pady=self.px(5))
        label = tk.Label(item, text=name, font=(theme.FONT, 10), background=palette.side, foreground=palette.ink, anchor="w")
        label.grid(row=0, column=1, sticky="ew")
        total = tk.Label(item, text="", font=(theme.FONT, 9), background=palette.side, foreground=palette.muted, anchor="e")
        total.grid(row=0, column=2, padx=(self.px(4), self.px(8)))
        parts = (item, symbol, label, total)

        def paint(color):
            for part in parts:
                part.configure(background=color)

        def enter(event):
            if self.show.get() != name:
                paint(palette.hover)

        def leave(event):
            if self.show.get() != name:
                paint(palette.side)

        for part in parts:
            part.bind("<Button-1>", lambda event: self.select_view(name))
            part.bind("<Enter>", enter)
            part.bind("<Leave>", leave)
        item.bind("<Return>", lambda event: self.select_view(name))
        item.bind("<space>", lambda event: self.select_view(name))
        self.nav[name] = (paint, symbol, label, total)
        return item

    def _build_header(self, parent):
        header = ttk.Frame(parent)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        self.title_label = ttk.Label(header, style="Title.TLabel")
        self.title_label.grid(row=0, column=0, sticky="w")
        self.hint_label = ttk.Label(header, style="Muted.TLabel")
        self.hint_label.grid(row=1, column=0, sticky="w", pady=(self.px(1), 0))
        controls = ttk.Frame(header)
        controls.grid(row=0, column=1, rowspan=2, sticky="e")
        ttk.Label(controls, text="Move to", style="Muted.TLabel").pack(side="left", padx=(0, self.px(6)))
        self.drive = ttk.Combobox(controls, state="readonly", width=30)
        self.drive.pack(side="left")
        self.drive.bind("<<ComboboxSelected>>", self._on_drive_chosen)
        search_row = ttk.Frame(parent)
        search_row.grid(row=1, column=0, sticky="ew", pady=(self.px(12), self.px(8)))
        search_row.columnconfigure(1, weight=1)
        ttk.Label(search_row, text="\ue721", font=(theme.ICONS, 10), style="Muted.TLabel").grid(row=0, column=0, padx=(self.px(2), self.px(8)))
        self.search_entry = ttk.Entry(search_row, textvariable=self.search)
        self.search_entry.grid(row=0, column=1, sticky="ew")
        self.search_hint = tk.Label(self.search_entry, text="Filter by name or path", background=self.palette.raised, foreground=self.palette.muted, font=(theme.FONT, 10))
        self.search_hint.place(x=self.px(6), rely=0.5, anchor="w")
        self.search_hint.bind("<Button-1>", lambda event: self.search_entry.focus_set())
        self.search.trace_add("write", lambda *ignored: self._on_search())
        self.scan_button = ttk.Button(search_row, text="Scan again", command=self.start_scan)
        self.scan_button.grid(row=0, column=2, padx=(self.px(8), 0))
        self.add_button = ttk.Button(search_row, text="Add folder", command=self.add_folder)
        self.add_button.grid(row=0, column=3, padx=(self.px(6), 0))
        self.space_drive = ttk.Combobox(search_row, state="readonly", width=6)
        self.space_button = ttk.Button(search_row, text="Scan drive", style="Primary.TButton", command=self.start_space)
        self.total = ttk.Label(search_row, style="Muted.TLabel")
        self.total.grid(row=0, column=6, padx=(self.px(12), 0))

    def _on_search(self):
        if self.search.get():
            self.search_hint.place_forget()
        else:
            self.search_hint.place(x=self.px(6), rely=0.5, anchor="w")
        self._refresh_rows()

    def _build_files_bar(self, parent):
        self.files_bar = ttk.Frame(parent)
        self.files_bar.columnconfigure(2, weight=1)
        self.up_button = ttk.Button(self.files_bar, text=ICON_UP, style="TButton", width=3, command=self.go_up)
        self.up_button.configure(style="TButton")
        self.up_button.grid(row=0, column=0, padx=(0, self.px(8)))
        self.path_label = ttk.Label(self.files_bar, style="Muted.TLabel")
        self.path_label.grid(row=0, column=2, sticky="ew")
        self.place_row = ttk.Frame(self.files_bar)
        self.place_row.grid(row=1, column=0, columnspan=3, sticky="w", pady=(self.px(8), 0))

    def _build_table(self, parent):
        palette = self.palette
        table = ttk.Frame(parent)
        table.grid(row=3, column=0, sticky="nsew")
        table.columnconfigure(0, weight=1)
        table.rowconfigure(0, weight=1)
        columns = ("pick", "name", "size", "status", "path")
        self.tree = ttk.Treeview(table, columns=columns, show="headings", selectmode="extended")
        for column, title, width, anchor, stretch in (
            ("pick", UNCHECKED, 36, "center", False),
            ("name", "Name", 260, "w", False),
            ("size", "Size", 84, "e", False),
            ("status", "Status", 118, "w", False),
            ("path", "Location", 400, "w", True),
        ):
            self.tree.heading(column, text=title, anchor="center" if column == "pick" else anchor, command=lambda chosen=column: self._on_heading(chosen))
            self.tree.column(column, width=self.px(width), minwidth=self.px(width // 2), anchor=anchor, stretch=stretch)
        self.tree.tag_configure("moved", foreground=palette.accent)
        self.tree.tag_configure("muted", foreground=palette.muted)
        self.tree.tag_configure("paused", foreground=palette.attention)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.bind("<Button-1>", self._on_click)
        self.tree.bind("<Double-1>", self._on_double)
        self.tree.bind("<space>", self._on_space)
        self.tree.bind("<Return>", self._on_double)
        self.tree.bind("<BackSpace>", lambda event: self.go_up())
        self.tree.bind("<Delete>", lambda event: self.start_delete())
        self.tree.bind("<Button-3>", self._on_menu)
        self.empty_label = ttk.Label(table, style="Empty.TLabel")
        self.row_menu = tk.Menu(self, tearoff=0, background=palette.raised, foreground=palette.ink, activebackground=palette.selected, activeforeground=palette.ink, borderwidth=0)

    def _build_actions(self, parent):
        bar = ttk.Frame(parent)
        bar.grid(row=4, column=0, sticky="ew", pady=(self.px(12), 0))
        bar.columnconfigure(0, weight=1)
        self.selection_label = ttk.Label(bar, style="Muted.TLabel")
        self.selection_label.grid(row=0, column=0, sticky="w")
        buttons = ttk.Frame(bar)
        buttons.grid(row=0, column=1, sticky="e")
        self.buttons_frame = buttons
        self.move_button = ttk.Button(buttons, text="Move selected", style="Primary.TButton", command=self.start_move)
        self.move_all_button = ttk.Button(buttons, text="Move everything shown", command=self.start_move_everything)
        self.undo_button = ttk.Button(buttons, text="Undo", command=self.start_undo)
        self.delete_button = ttk.Button(buttons, text="Delete\u2026", command=self.start_delete)
        self.uninstall_button = ttk.Button(buttons, text="Uninstall\u2026", command=self.start_uninstall)
        self.finish_button = ttk.Button(buttons, text="Delete old copies", command=self.start_finish)
        self.clear_button = ttk.Button(buttons, text="Clear selected", style="Primary.TButton", command=self.start_clear)
        self.remove_links = tk.BooleanVar(value=False)
        self.remove_links_check = ttk.Checkbutton(buttons, text="Also remove links that aren't needed", variable=self.remove_links)
        self.stop_button = ttk.Button(buttons, text="Stop", command=self.cancel.set)
        self.progress = ttk.Progressbar(parent, maximum=100)
        self.progress_shown = False
        status = ttk.Frame(parent)
        status.grid(row=6, column=0, sticky="ew", pady=(self.px(8), 0))
        status.columnconfigure(0, weight=1)
        self.status_label = ttk.Label(status, style="Muted.TLabel", anchor="w")
        self.status_label.grid(row=0, column=0, sticky="ew")
        self.activity_button = ttk.Button(status, text="Activity", style="Ghost.TButton", command=self.toggle_activity)
        self.activity_button.grid(row=0, column=1, sticky="e")
        self.log = tk.Text(parent, height=6, wrap="word", state="disabled", relief="flat", font=(theme.FONT, 9), background=self.palette.raised, foreground=self.palette.ink, padx=self.px(10), pady=self.px(8), highlightthickness=0, borderwidth=0)
        self.activity_shown = False

    def toggle_activity(self):
        self.activity_shown = not self.activity_shown
        if self.activity_shown:
            self.log.grid(row=7, column=0, sticky="ew", pady=(self.px(6), 0))
        else:
            self.log.grid_remove()

    def _load_drives(self):
        try:
            self.drives = volumes.list_drives(include_removable=True)
        except OSError:
            self.drives = []
        system = os.environ.get("SystemDrive", "C:").upper()
        labels = []
        for drive in self.drives:
            kind = "USB drive" if drive.removable else (drive.label or "Local Disk")
            labels.append(f"{drive.letter}:  {kind}  ({volumes.format_size(drive.free)} free)")
        custom = self.destination if self.destination and not any(self.destination == drive.root for drive in self.drives) else None
        values = labels + ([custom] if custom else []) + [CHOOSE_FOLDER]
        self.drive["values"] = values
        if self.destination is None:
            for drive in self.drives:
                if f"{drive.letter}:" != system and not drive.removable:
                    self.destination = drive.root
                    break
            else:
                self.destination = self.drives[0].root if self.drives else None
        self._select_destination()
        self.space_drive["values"] = [f"{drive.letter}:" for drive in self.drives]
        if self.drives and not self.space_drive.get():
            self.space_drive.set(system if any(f"{drive.letter}:" == system for drive in self.drives) else f"{self.drives[0].letter}:")
        self._paint_drives()

    def _select_destination(self):
        for index, drive in enumerate(self.drives):
            if drive.root == self.destination:
                self.drive.current(index)
                return
        if self.destination:
            self.drive.set(self.destination)

    def _paint_drives(self):
        palette = self.palette
        for widget in self.drive_panel.winfo_children():
            widget.destroy()
        for row, drive in enumerate(self.drives):
            used = 1 - drive.free / drive.total if drive.total else 0
            line = tk.Frame(self.drive_panel, background=palette.side, cursor="hand2")
            line.grid(row=row, column=0, sticky="ew", pady=(0, self.px(10)))
            line.columnconfigure(0, weight=1)
            name = tk.Label(line, text=f"{drive.letter}:  {drive.label or 'Local Disk'}", background=palette.side, foreground=palette.ink, font=(theme.FONT, 9), anchor="w")
            name.grid(row=0, column=0, sticky="ew")
            height = self.px(5)
            bar = tk.Canvas(line, height=height, background=palette.track, highlightthickness=0, borderwidth=0)
            bar.grid(row=1, column=0, sticky="ew", pady=self.px(3))
            color = palette.attention if drive.free / max(drive.total, 1) < 0.1 else palette.accent
            bar.bind("<Configure>", lambda event, canvas=bar, share=used, fill=color: self._paint_bar(canvas, event.width, share, fill))
            detail = tk.Label(line, text=f"{volumes.format_size(drive.free)} free of {volumes.format_size(drive.total)}", background=palette.side, foreground=palette.muted, font=(theme.FONT, 9), anchor="w")
            detail.grid(row=2, column=0, sticky="ew")
            for part in (line, name, bar, detail):
                part.bind("<Button-1>", lambda event, root=drive.root: self.browse(root))

    def _paint_bar(self, canvas, width, share, color):
        canvas.delete("all")
        canvas.create_rectangle(0, 0, max(1, int(width * share)), self.px(6), fill=color, width=0)

    def _on_drive_chosen(self, event=None):
        index = self.drive.current()
        values = self.drive["values"]
        if index >= 0 and values[index] == CHOOSE_FOLDER:
            chosen = filedialog.askdirectory(title="Choose where to move things")
            if chosen:
                self.destination = os.path.normpath(chosen)
                self._load_drives()
            else:
                self._select_destination()
            self._refresh_rows()
            return
        if 0 <= index < len(self.drives):
            self.destination = self.drives[index].root
        self._refresh_rows()

    def selected_root(self):
        return self.destination

    def _destination_drive(self):
        root = self.selected_root()
        return volumes.drive_of(root) if root else ""

    def select_view(self, name):
        previous = self.show.get()
        self.show.set(name)
        palette = self.palette
        for key, (paint, symbol, label, _) in self.nav.items():
            active = key == name
            paint(palette.selected if active else palette.side)
            symbol.configure(foreground=palette.accent if active else palette.muted)
            label.configure(font=(theme.SEMIBOLD if active else theme.FONT, 10))
        self.title_label.configure(text=name)
        self.hint_label.configure(text=HINTS.get(name, ""))
        self._layout_view(name)
        if name == FILES and (self.folder is None or previous != FILES):
            self.browse(self.folder or self._default_folder())
        elif name == MOVED:
            self._load_moved()
        self._refresh_rows()

    def _default_folder(self):
        for label, path in browser.places():
            if label == "Downloads":
                return path
        return os.environ.get("USERPROFILE", "C:\\")

    def _layout_view(self, name):
        self.scan_button.grid_remove()
        self.add_button.grid_remove()
        self.space_drive.grid_remove()
        self.space_button.grid_remove()
        self.files_bar.grid_remove()
        if name == LARGE:
            self.space_drive.grid(row=0, column=4, padx=(self.px(8), 0))
            self.space_button.grid(row=0, column=5, padx=(self.px(6), 0))
        elif name == FILES:
            self.files_bar.grid(row=2, column=0, sticky="ew", pady=(0, self.px(8)))
            self._paint_places()
        elif name != MOVED:
            self.scan_button.grid()
            self.add_button.grid()
        self._layout_buttons(name)

    def _layout_buttons(self, name):
        buttons = (self.move_button, self.move_all_button, self.undo_button, self.delete_button, self.uninstall_button, self.finish_button, self.clear_button, self.remove_links_check, self.stop_button)
        for button in buttons:
            button.pack_forget()
        if self.working:
            self.stop_button.pack(side="left")
            return
        order = {
            DEVELOPER: (self.undo_button, self.delete_button, self.move_all_button, self.move_button),
            GAMES: (self.undo_button, self.uninstall_button, self.move_all_button, self.move_button),
            APPS: (self.undo_button, self.uninstall_button, self.move_all_button, self.move_button),
            DATA: (self.undo_button, self.delete_button, self.move_all_button, self.move_button),
            PERSONAL: (self.undo_button, self.move_button),
            STORE: (self.undo_button, self.uninstall_button, self.move_button),
            LARGE: (self.undo_button, self.delete_button, self.move_button),
            FILES: (self.delete_button, self.move_button),
            CACHES: (self.clear_button,),
            MOVED: (self.remove_links_check, self.finish_button, self.undo_button),
        }
        for button in order.get(name, ()):
            button.pack(side="left", padx=(self.px(6), 0))

    def _paint_places(self):
        for widget in self.place_row.winfo_children():
            widget.destroy()
        try:
            places = browser.places()
        except OSError:
            places = []
        for label, path in places:
            ttk.Button(self.place_row, text=label, style="Ghost.TButton", command=lambda chosen=path: self.browse(chosen)).pack(side="left", padx=(0, self.px(2)))

    def browse(self, path):
        if self.show.get() != FILES:
            self.folder = path
            self.select_view(FILES)
            return
        try:
            entries = browser.list_folder(path)
        except OSError as error:
            self.write(f"Couldn't open {path}: {error}")
            return
        self.folder = path
        self.path_label.configure(text=path)
        for row in [row for row, found in self.rows.items() if found.category == FILES]:
            self.rows.pop(row)
            self.checked.discard(row)
        found_items = []
        for entry in entries:
            cached = self.sizes.get(entry.path) if entry.is_folder else None
            size = cached[0] if cached else entry.size
            found = Found(entry.path, entry.name, entry.path, size, "ready", category=FILES, is_item=True, is_folder=entry.is_folder, pending=entry.is_folder)
            self.rows[found.id] = found
            if entry.is_folder:
                found_items.append(found)
        self._refresh_rows()
        self._start_sizing(found_items)

    def go_up(self):
        if self.show.get() != FILES or not self.folder:
            return
        parent = browser.parent_of(self.folder)
        if parent:
            self.browse(parent)

    def write(self, message):
        self.log.configure(state="normal")
        self.log.insert("end", message + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")
        self.status_label.configure(text=message.splitlines()[0] if message else "")

    def _on_heading(self, column):
        if column == "pick":
            shown = [row for row in self.tree.get_children() if row in self.rows and self.rows[row].status in TICKABLE]
            everything = bool(shown) and all(row in self.checked for row in shown)
            for row in shown:
                if everything == (row in self.checked):
                    self.toggle(row)
            return
        if self.sort_column == column:
            self.sort_reverse = not self.sort_reverse
        else:
            self.sort_column = column
            self.sort_reverse = column == "size"
        self._refresh_rows()

    def _on_click(self, event):
        row = self.tree.identify_row(event.y)
        if row and self.tree.identify_column(event.x) == "#1":
            self.toggle(row)

    def _on_space(self, event):
        for row in self.tree.selection():
            self.toggle(row)
        return "break"

    def _on_double(self, event):
        selection = self.tree.selection()
        row = self.tree.identify_row(event.y) if event.y else (selection[0] if selection else "")
        if not row or row not in self.rows:
            return
        found = self.rows[row]
        if found.category == PERSONAL:
            self.browse(found.source)
        elif found.category == FILES:
            if found.is_folder:
                self.browse(found.source)
            else:
                actions.reveal(found.source)
        elif found.status in TICKABLE:
            self.toggle(row)

    def _on_menu(self, event):
        row = self.tree.identify_row(event.y)
        if not row:
            return
        if row not in self.tree.selection():
            self.tree.selection_set(row)
        found = self.rows[row]
        menu = self.row_menu
        menu.delete(0, "end")
        menu.add_command(label="Show in File Explorer", command=lambda src=found.source: actions.reveal(src))
        menu.add_command(label="Copy path", command=lambda src=found.source: self._copy_path(src))
        if found.category in (DEVELOPER, DATA, LARGE, FILES) and found.status in MOVABLE:
            menu.add_separator()
            menu.add_command(label="Delete\u2026", command=self.start_delete)
        if found.category in (APPS, GAMES, STORE):
            menu.add_separator()
            menu.add_command(label="Uninstall\u2026", command=lambda item=found: self.start_uninstall([item]))
        menu.tk_popup(event.x_root, event.y_root)

    def _copy_path(self, path):
        self.clipboard_clear()
        self.clipboard_append(path)
        self.write("Copied the path.")

    def _tag_of(self, found):
        if found.status in ("moved", "finished"):
            return ("moved",)
        if found.status == PAUSED:
            return ("paused",)
        if found.status == STAYS or self._already_there(found) or found.status == "linked elsewhere":
            return ("muted",)
        return ()

    def _already_there(self, found):
        if self.allow_same_drive or found.status not in MOVABLE or found.source.startswith("\\\\"):
            return False
        return bool(self._destination_drive()) and volumes.drive_of(found.source) == self._destination_drive()

    def _status_text(self, found):
        if self._already_there(found):
            return f"already on {self._destination_drive()}"
        return "" if found.status == "ready" else found.status

    def toggle(self, row):
        found = self.rows[row]
        if found.status == STAYS:
            self.write(f"{found.name} stays put: {found.reason}.")
            return
        if self._already_there(found):
            self.write(f"{found.name} is already on {self._destination_drive()}. Choose another drive under Move to.")
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
        self._update_selection()

    def _visible(self, found):
        view = self.show.get()
        if found.hidden or found.category != view:
            return False
        if found.pending and found.minimum and found.size < found.minimum:
            return False
        text = self.search.get().strip().lower()
        return not text or text in found.name.lower() or text in found.source.lower()

    def _values(self, found):
        pick = CHECKED if found.id in self.checked else UNCHECKED
        return (pick, found.name, format_size(found), self._status_text(found), found.source)

    def _sort_key(self, found):
        if self.show.get() == FILES and self.sort_column == "name":
            return (not found.is_folder, found.name.lower())
        if self.sort_column == "size":
            return found.size
        if self.sort_column == "status":
            return found.status
        if self.sort_column == "path":
            return found.source.lower()
        return found.name.lower()

    def _update_total(self):
        shown = [item for item in self.rows.values() if self._visible(item)]
        ready = sum(item.size for item in shown if item.status in MOVABLE and not self._already_there(item))
        clearable = sum(item.size for item in shown if item.status == CAN_CLEAR)
        text = f"{volumes.format_size(ready)} can be moved" if ready else ""
        if clearable:
            text = f"{volumes.format_size(clearable)} can be cleared"
        self.total.configure(text=text)
        for view, (_, _, _, label) in self.nav.items():
            if view in (FILES, LARGE):
                continue
            items = [item for item in self.rows.values() if item.category == view and not item.hidden]
            if view == MOVED:
                label.configure(text=str(len(items)) if items else "")
            elif view == CACHES:
                size = sum(item.size for item in items)
                label.configure(text=volumes.format_size(size) if size else "")
            else:
                size = sum(item.size for item in items if item.status in MOVABLE and not self._already_there(item))
                label.configure(text=volumes.format_size(size) if size else "")
        self._update_selection()

    def _update_selection(self):
        chosen = [self.rows[row] for row in self.checked if row in self.rows and self._visible(self.rows[row])]
        if chosen:
            size = volumes.format_size(sum(item.size for item in chosen))
            self.selection_label.configure(text=f"{len(chosen)} selected, {size}")
        else:
            self.selection_label.configure(text="Tick items to act on them.")
        destination = self.selected_root()
        if destination:
            drive = volumes.drive_of(destination)
            target = f"{drive}" if os.path.dirname(destination.rstrip(chr(92)) + chr(92)) == destination.rstrip(chr(92)) + chr(92) else destination
            self.move_button.configure(text=f"Move to {target}")

    def _refresh_rows(self):
        self.tree.delete(*self.tree.get_children())
        shown = [found for found in self.rows.values() if self._visible(found)]
        reverse = self.sort_reverse
        shown.sort(key=self._sort_key, reverse=reverse)
        for found in shown:
            self.tree.insert("", "end", iid=found.id, values=self._values(found), tags=self._tag_of(found))
        self._update_headings()
        self._update_empty(bool(shown))
        self._update_total()

    def _update_headings(self):
        titles = {"name": "Name", "size": "Size", "status": "Status", "path": "Location"}
        for column, title in titles.items():
            mark = (" \u2193" if self.sort_reverse else " \u2191") if column == self.sort_column else ""
            self.tree.heading(column, text=title + mark)

    def _update_empty(self, has_rows):
        if has_rows:
            self.empty_label.place_forget()
            return
        view = self.show.get()
        text = "Nothing matches that search." if self.search.get().strip() else EMPTY.get(view, "")
        if self.working and view != FILES:
            text = "Looking\u2026"
        self.empty_label.configure(text=text)
        self.empty_label.place(relx=0.5, rely=0.35, anchor="center")

    def _show_found(self, found):
        self.rows[found.id] = found
        if self._visible(found):
            if self.tree.exists(found.id):
                self.tree.item(found.id, values=self._values(found), tags=self._tag_of(found))
            else:
                self.tree.insert("", "end", iid=found.id, values=self._values(found), tags=self._tag_of(found))
                self._update_empty(True)
            self.needs_sort = True
        elif self.tree.exists(found.id):
            self.tree.delete(found.id)
        self._update_total()

    def _periodic_sort(self):
        if self.needs_sort:
            self.needs_sort = False
            selection = self.tree.selection()
            top = self.tree.yview()[0]
            shown = [self.rows[row] for row in self.tree.get_children() if row in self.rows]
            shown.sort(key=self._sort_key, reverse=self.sort_reverse)
            for index, found in enumerate(shown):
                self.tree.move(found.id, "", index)
            if selection:
                self.tree.selection_set(*[row for row in selection if self.tree.exists(row)])
            self.tree.yview_moveto(top)
        self.sort_poll = self.after(400, self._periodic_sort)

    def _set_working(self, working):
        self.working = working
        state = "disabled" if working else "normal"
        for button in (self.scan_button, self.space_button, self.add_button):
            button.configure(state=state)
        if working and not self.progress_shown:
            self.progress.grid(row=5, column=0, sticky="ew", pady=(self.px(10), 0))
            self.progress_shown = True
        elif not working and self.progress_shown:
            self.progress.grid_remove()
            self.progress_shown = False
            self.progress["value"] = 0
        self._layout_buttons(self.show.get())

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
        handled = 0
        try:
            while handled < 300:
                kind, value = self.events.get_nowait()
                handled += 1
                if kind == "found":
                    self._show_found(value)
                elif kind == "log":
                    self.write(value)
                elif kind == "progress":
                    self.progress["value"] = value
                elif kind == "view":
                    self.select_view(value)
                elif kind == "reset":
                    keep = {row: found for row, found in self.rows.items() if found.category in (FILES, LARGE)}
                    self.rows = keep
                    self.checked &= set(keep)
                elif kind == "refresh":
                    self._refresh_rows()
                elif kind == "moved":
                    self._load_moved()
                elif kind == "drives":
                    self._load_drives()
                elif kind == "folder":
                    if self.folder and self.show.get() == FILES:
                        self.browse(self.folder)
                elif kind == "sizing":
                    self.sizing = value
                elif kind == "done":
                    self._set_working(False)
                    self._update_empty(bool(self.tree.get_children()))
        except queue.Empty:
            pass
        self.poll = self.after(40, self._drain)

    def _report_progress(self, done, total):
        self.events.put(("progress", (done * 100 / total) if total else 0))

    def _load_moved(self):
        for row in [row for row, found in self.rows.items() if found.category == MOVED]:
            self.rows.pop(row)
            self.checked.discard(row)
        for record in self.journal.records():
            status = PAUSED if record["state"] == PAUSED else ("finished" if record["state"] == "finished" else "moved")
            found = Found(f"record:{record['id']}", record["name"], record["target"], record.get("bytes", 0), status, category=MOVED, record_id=record["id"])
            self.rows[found.id] = found
        self._refresh_rows()

    def _scan_work(self):
        self.events.put(("reset", None))
        self.generation += 1
        found = discover(
            self.journal,
            self.tools,
            self.include_wsl,
            lambda item: self.events.put(("found", item)),
            self.include_installed,
            None,
            self.sizes,
        )
        records = self.journal.records()
        extra = []
        for record in records:
            if record.get("kind") == "content" or any(self._matches(item, record) for item in found):
                continue
            category = record.get("category", DEVELOPER)
            status = PAUSED if record["state"] == PAUSED else "moved"
            item = Found(record["source"], record["name"], record["source"], record.get("bytes", 0), status, category=category)
            extra.append(item)
            self.events.put(("found", item))
        states = {record["source"].lower(): record["state"] for record in records}
        for item in self.large:
            state = states.get(item.source.lower())
            if state:
                item.status = PAUSED if state == PAUSED else "moved"
            elif item.status in ("moved", PAUSED):
                item.status = "ready"
            self.events.put(("found", item))
        self.events.put(("moved", None))
        self.events.put(("drives", None))
        self.events.put(("folder", None))
        self._start_sizing([item for item in found if item.pending])

    def _start_sizing(self, items):
        if not items:
            return
        self.generation += 1
        generation = self.generation
        self.sizing = True

        def one(item):
            if generation != self.generation:
                return
            settle(item, self.sizes)
            if generation == self.generation:
                self.events.put(("found", item))

        def body():
            try:
                with ThreadPoolExecutor(WORKERS) as pool:
                    list(pool.map(one, items))
                self.sizes.save()
            finally:
                if generation == self.generation:
                    self.events.put(("sizing", False))

        threading.Thread(target=body, daemon=True).start()

    @staticmethod
    def _matches(item, record):
        if record.get("distro") and item.distro == record["distro"]:
            return True
        if record.get("known") and item.known == record["known"]:
            return True
        if record.get("package") and item.package == record["package"]:
            return True
        return item.source.lower() == record["source"].lower() and item.status not in MOVABLE

    def start_scan(self):
        self._run(self._scan_work)

    def recover_and_scan(self):
        def work():
            for message in actions.recover(self.journal, self.store):
                self.events.put(("log", message))
            self._scan_work()

        self._run(work)

    def start_space(self):
        chosen = self.space_drive.get()
        root = getattr(self, "space_root", None) or (f"{chosen}\\" if chosen else f"{os.environ.get('SystemDrive', 'C:')}\\")

        def work():
            self.events.put(("log", f"Reading {root}. This can take a little while."))
            self.events.put(("view", LARGE))
            for row in [row for row, found in self.rows.items() if found.category == LARGE]:
                self.rows.pop(row, None)
            self.large = spacefinder.find(root, self.journal, self.space_minimum, cancel=self.cancel)
            for item in self.large:
                self.events.put(("found", item))
            self.events.put(("log", f"Found {len(self.large)} large items on {root}."))

        self._run(work)

    def add_folder(self):
        path = filedialog.askdirectory(title="Choose a folder to move")
        if path:
            self.add_path(path)

    def add_path(self, path):
        clean = os.path.normpath(path)
        found = Found(clean, os.path.basename(clean), clean, 0, "ready", pending=True)
        self.select_view(DEVELOPER)
        self._show_found(found)
        self.toggle(clean)
        self._start_sizing([found])

    def _chosen(self, *statuses):
        return [self.rows[row] for row in self.checked if row in self.rows and self.rows[row].status in statuses and self._visible(self.rows[row])]

    def _record_for(self, found):
        if found.record_id:
            try:
                return self.journal.get(found.record_id)
            except KeyError:
                return None
        for record in self.journal.records():
            if self._matches(found, record):
                return record
        return None

    def _confirm(self, title, body, choices):
        dialog = Confirm(self.master, self.palette, title, body, choices)
        self.master.wait_window(dialog)
        return dialog.result

    def start_move_everything(self, ask=True):
        ready = [found for found in self.rows.values() if found.status in MOVABLE and self._visible(found) and not self._already_there(found)]
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
        message = f"{len(chosen)} items ({size}) will move to {root}. Close them first, because anything still open stays where it is."
        if left:
            names = ", ".join(found.name for found in left[:5])
            more = f" and {len(left) - 5} more" if len(left) > 5 else ""
            caches_size = sum(found.size for found in self.rows.values() if found.status == CAN_CLEAR)
            message += f"\n\nThese won't fit and stay put: {names}{more}."
            if caches_size:
                message += f"\nClearing caches would free {volumes.format_size(caches_size)} with nothing to move."
        if ask and self._confirm("Move everything shown", message, [("Cancel", None), ("Move", True)]) is None:
            return
        for found in left:
            self.write(f"{found.name} ({volumes.format_size(found.size)}) doesn't fit on {root}, so it stays.")
        for row in list(self.checked):
            if row in self.rows and self.rows[row] in left:
                self.toggle(row)
        for found in chosen:
            if found.id not in self.checked:
                self.toggle(found.id)
        self.start_move()

    def start_move(self):
        root = self.selected_root()
        chosen = [found for found in self._chosen(*MOVABLE) if not self._already_there(found)]
        relocating = self._chosen("moved", "finished")
        if not chosen and not relocating:
            self.write("Tick at least one item that's ready to move.")
            return
        if root is None:
            self.write("Choose a drive to move to.")
            return
        destination = volumes.drive_of(root)

        def work():
            for found in relocating:
                if self.cancel.is_set():
                    break
                record = self._record_for(found)
                if record is None or volumes.drive_of(record["target"]) == destination:
                    self.events.put(("log", f"{found.name} is already on {destination}."))
                    continue
                self.events.put(("log", f"Moving {found.name} to {destination}\u2026"))
                try:
                    self.events.put(("log", actions.relocate(found, record, root, self.journal, self.store, self._report_progress, self.cancel)))
                except Cancelled:
                    self.events.put(("log", f"{found.name}: stopped."))
                except actions.ERRORS as error:
                    self.events.put(("log", f"{found.name} wasn't moved: {error}"))
            for found in chosen:
                if self.cancel.is_set():
                    break
                self.events.put(("log", f"Moving {found.name}\u2026"))
                self.events.put(("progress", 0))
                try:
                    record = actions.move_found(found, root, self.journal, self.store, self._report_progress, self.cancel)
                    self.events.put(("log", f"{found.name} moved to {record['target']}."))
                    if record.get("note"):
                        self.events.put(("log", record["note"]))
                except Cancelled:
                    if found.is_item:
                        self.events.put(("log", f"{found.name}: stopped, and nothing was changed."))
                    else:
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
                self.events.put(("log", f"Moving {found.name} back\u2026"))
                try:
                    self.events.put(("log", actions.undo_record(record, self.journal, self.store, self._report_progress, self.cancel)))
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
        if ask and self._confirm(
            "Delete old copies",
            f"Check that everything still works first. This deletes {len(records)} old copies and frees their space. Undo will still work.",
            [("Cancel", None), ("Delete old copies", True)],
        ) is None:
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
            self.write("Tick the caches you want to clear.")
            return
        size = volumes.format_size(sum(found.size for found in chosen))
        if ask and self._confirm(
            "Clear caches",
            f"This deletes {size} from {len(chosen)} caches. It can't be undone, but your tools download or rebuild them when needed.",
            [("Cancel", None), ("Clear", True)],
        ) is None:
            return

        def work():
            for found in chosen:
                try:
                    self.events.put(("log", actions.clear_cache(found)))
                except actions.ERRORS as error:
                    self.events.put(("log", f"{found.name}: {error}"))
            self._scan_work()

        self._run(work)

    def start_delete(self, answer=None):
        view = self.show.get()
        if view not in (DEVELOPER, DATA, LARGE, FILES):
            return
        chosen = self._chosen(*MOVABLE)
        if not chosen:
            selection = [self.rows[row] for row in self.tree.selection() if row in self.rows and self.rows[row].status in MOVABLE]
            chosen = selection
        if not chosen:
            self.write("Tick what you want to delete.")
            return
        size = volumes.format_size(sum(found.size for found in chosen))
        names = ", ".join(found.name for found in chosen[:4])
        more = f" and {len(chosen) - 4} more" if len(chosen) > 4 else ""
        choice = answer
        if choice is None:
            choice = self._confirm(
                "Delete",
                f"{names}{more} ({size}). The Recycle Bin lets you restore them, but the space only comes back once it's emptied.",
                [("Cancel", None), ("Delete permanently", "permanent"), ("Move to Recycle Bin", "recycle")],
            )
        if choice is None:
            return
        permanently = choice == "permanent"

        def work():
            for found in chosen:
                try:
                    self.events.put(("log", actions.delete_found(found, self.journal, permanently)))
                except actions.ERRORS as error:
                    self.events.put(("log", f"{found.name} wasn't deleted: {error}"))
            self.checked.difference_update(found.id for found in chosen)
            if view == FILES:
                self.events.put(("folder", None))
                self.events.put(("drives", None))
            else:
                self._scan_work()

        self._run(work)

    def start_uninstall(self, chosen=None):
        items = chosen or self._chosen(*MOVABLE, "moved", "finished", STAYS) or [self.rows[row] for row in self.tree.selection() if row in self.rows]
        if not items:
            self.write("Tick what you want to uninstall.")
            return
        for found in items:
            try:
                self.write(actions.uninstall(found))
            except actions.ERRORS as error:
                self.write(f"{found.name}: {error}")


def main():
    admin = elevation.is_admin()
    if not admin and elevation.relaunch():
        return 0
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except OSError:
        pass
    root = tk.Tk()
    root.withdraw()
    app = App(root)
    root.update_idletasks()
    theme.dark_title_bar(root, app.palette.name == "dark")
    root.deiconify()
    if not admin:
        app.write("Running without administrator rights, so anything in Program Files can't be moved.")
    root.mainloop()
    return 0
