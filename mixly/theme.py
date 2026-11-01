import ctypes
import math
import tkinter as tk
import winreg
from dataclasses import dataclass
from tkinter import font as tkfont
from tkinter import ttk

HUE = 145
FONT = "Segoe UI"
SEMIBOLD = "Segoe UI Semibold"
ICONS = "Segoe MDL2 Assets"
DWMWA_USE_IMMERSIVE_DARK_MODE = 20


def oklch(lightness, chroma, hue):
    angle = math.radians(hue)
    a, b = chroma * math.cos(angle), chroma * math.sin(angle)
    long = (lightness + 0.3963377774 * a + 0.2158037573 * b) ** 3
    middle = (lightness - 0.1055613458 * a - 0.0638541728 * b) ** 3
    short = (lightness - 0.0894841775 * a - 1.2914855480 * b) ** 3
    linear = (
        4.0767416621 * long - 3.3077115913 * middle + 0.2309699292 * short,
        -1.2684380046 * long + 2.6097574011 * middle - 0.3413193965 * short,
        -0.0041960863 * long - 0.7034186147 * middle + 1.7076147010 * short,
    )
    channels = []
    for value in linear:
        clipped = min(max(value, 0.0), 1.0)
        encoded = 12.92 * clipped if clipped <= 0.0031308 else 1.055 * clipped ** (1 / 2.4) - 0.055
        channels.append(round(encoded * 255))
    return "#{:02x}{:02x}{:02x}".format(*channels)


def _luminance(color):
    channels = []
    for start in (1, 3, 5):
        value = int(color[start:start + 2], 16) / 255
        channels.append(value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4)
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def contrast(first, second):
    high, low = sorted((_luminance(first), _luminance(second)), reverse=True)
    return (high + 0.05) / (low + 0.05)


@dataclass(frozen=True)
class Palette:
    name: str
    surface: str
    side: str
    raised: str
    hover: str
    line: str
    ink: str
    muted: str
    accent: str
    accent_hover: str
    on_accent: str
    selected: str
    track: str
    attention: str
    problem: str


LIGHT = Palette(
    "light",
    surface=oklch(1.0, 0, HUE),
    side=oklch(0.967, 0.005, HUE),
    raised=oklch(0.985, 0.003, HUE),
    hover=oklch(0.93, 0.008, HUE),
    line=oklch(0.89, 0.007, HUE),
    ink=oklch(0.24, 0.012, HUE),
    muted=oklch(0.47, 0.012, HUE),
    accent=oklch(0.46, 0.115, HUE),
    accent_hover=oklch(0.40, 0.105, HUE),
    on_accent=oklch(1.0, 0, HUE),
    selected=oklch(0.93, 0.035, HUE),
    track=oklch(0.88, 0.007, HUE),
    attention=oklch(0.50, 0.11, 70),
    problem=oklch(0.48, 0.15, 28),
)

DARK = Palette(
    "dark",
    surface=oklch(0.205, 0.006, HUE),
    side=oklch(0.175, 0.006, HUE),
    raised=oklch(0.24, 0.007, HUE),
    hover=oklch(0.265, 0.008, HUE),
    line=oklch(0.30, 0.008, HUE),
    ink=oklch(0.94, 0.006, HUE),
    muted=oklch(0.74, 0.01, HUE),
    accent=oklch(0.79, 0.13, HUE),
    accent_hover=oklch(0.85, 0.12, HUE),
    on_accent=oklch(0.2, 0.03, HUE),
    selected=oklch(0.31, 0.04, HUE),
    track=oklch(0.32, 0.008, HUE),
    attention=oklch(0.80, 0.12, 80),
    problem=oklch(0.76, 0.13, 28),
)


def windows_prefers_dark():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as key:
            return winreg.QueryValueEx(key, "AppsUseLightTheme")[0] == 0
    except OSError:
        return False


def current():
    return DARK if windows_prefers_dark() else LIGHT


def dark_title_bar(window, enabled):
    try:
        handle = ctypes.windll.user32.GetParent(window.winfo_id())
        value = ctypes.c_int(1 if enabled else 0)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(handle, DWMWA_USE_IMMERSIVE_DARK_MODE, ctypes.byref(value), ctypes.sizeof(value))
    except (OSError, AttributeError):
        pass


def scale_of(window):
    return window.winfo_fpixels("1i") / 96


def apply(window, palette):
    scale = scale_of(window)
    size = lambda value: round(value * scale)
    default = tkfont.nametofont("TkDefaultFont")
    default.configure(family=FONT, size=10)
    tkfont.nametofont("TkTextFont").configure(family=FONT, size=10)
    tkfont.nametofont("TkHeadingFont").configure(family=FONT, size=9)
    window.configure(background=palette.surface)
    style = ttk.Style(window)
    style.theme_use("clam")
    style.configure(".", background=palette.surface, foreground=palette.ink, font=(FONT, 10), borderwidth=0, focuscolor=palette.accent)
    style.configure("TFrame", background=palette.surface)
    style.configure("Side.TFrame", background=palette.side)
    style.configure("TLabel", background=palette.surface, foreground=palette.ink)
    style.configure("Muted.TLabel", background=palette.surface, foreground=palette.muted)
    style.configure("Title.TLabel", background=palette.surface, foreground=palette.ink, font=(SEMIBOLD, 16))
    style.configure("Empty.TLabel", background=palette.surface, foreground=palette.muted, font=(FONT, 10), justify="center")

    def button(name, background, foreground, hover, border, pressed=None):
        style.configure(name, background=background, foreground=foreground, bordercolor=border, lightcolor=background, darkcolor=background, borderwidth=1, relief="flat", padding=(size(12), size(6)), font=(FONT, 10), focuscolor=foreground, anchor="center")
        style.map(
            name,
            background=[("disabled", palette.raised), ("pressed", pressed or hover), ("active", hover)],
            foreground=[("disabled", palette.muted)],
            lightcolor=[("disabled", palette.raised), ("active", hover)],
            darkcolor=[("disabled", palette.raised), ("active", hover)],
            bordercolor=[("focus", palette.accent), ("disabled", palette.line)],
        )

    button("Primary.TButton", palette.accent, palette.on_accent, palette.accent_hover, palette.accent)
    button("TButton", palette.raised, palette.ink, palette.hover, palette.line)
    button("Ghost.TButton", palette.surface, palette.ink, palette.hover, palette.surface)
    style.configure("Primary.TButton", font=(SEMIBOLD, 10))
    style.configure("Ghost.TButton", padding=(size(8), size(4)), foreground=palette.muted)
    for name in ("Primary.TButton", "TButton", "Ghost.TButton"):
        style.configure(name, width=-1)

    style.configure("Treeview", background=palette.surface, fieldbackground=palette.surface, foreground=palette.ink, rowheight=size(30), borderwidth=0, font=(FONT, 10))
    style.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
    style.map("Treeview", background=[("selected", palette.selected)], foreground=[("selected", palette.ink)])
    style.configure("Treeview.Heading", background=palette.surface, foreground=palette.muted, relief="flat", borderwidth=0, padding=(size(6), size(6)), font=(FONT, 9), lightcolor=palette.surface, darkcolor=palette.surface, bordercolor=palette.line)
    style.map("Treeview.Heading", background=[("active", palette.hover)], foreground=[("active", palette.ink)])

    style.configure("TEntry", fieldbackground=palette.raised, foreground=palette.ink, bordercolor=palette.line, lightcolor=palette.raised, darkcolor=palette.raised, insertcolor=palette.ink, padding=size(5), borderwidth=1)
    style.map("TEntry", bordercolor=[("focus", palette.accent)], lightcolor=[("focus", palette.raised)], darkcolor=[("focus", palette.raised)])
    style.configure("TCombobox", fieldbackground=palette.raised, background=palette.raised, foreground=palette.ink, arrowcolor=palette.muted, bordercolor=palette.line, lightcolor=palette.raised, darkcolor=palette.raised, padding=size(5), borderwidth=1)
    style.map(
        "TCombobox",
        fieldbackground=[("readonly", palette.raised)],
        foreground=[("readonly", palette.ink)],
        selectbackground=[("readonly", palette.raised)],
        selectforeground=[("readonly", palette.ink)],
        background=[("active", palette.hover)],
        bordercolor=[("focus", palette.accent)],
    )
    window.option_add("*TCombobox*Listbox.background", palette.raised)
    window.option_add("*TCombobox*Listbox.foreground", palette.ink)
    window.option_add("*TCombobox*Listbox.selectBackground", palette.selected)
    window.option_add("*TCombobox*Listbox.selectForeground", palette.ink)
    window.option_add("*TCombobox*Listbox.font", (FONT, 10))
    window.option_add("*TCombobox*Listbox.borderWidth", 0)

    style.configure("TCheckbutton", background=palette.surface, foreground=palette.ink, indicatorbackground=palette.raised, indicatorforeground=palette.accent, bordercolor=palette.line, lightcolor=palette.raised, darkcolor=palette.raised, focuscolor=palette.accent, padding=size(2))
    style.map("TCheckbutton", background=[("active", palette.surface)], indicatorbackground=[("selected", palette.raised), ("active", palette.hover)])
    style.layout("Vertical.TScrollbar", [("Vertical.Scrollbar.trough", {"sticky": "ns", "children": [("Vertical.Scrollbar.thumb", {"expand": "1", "sticky": "nswe"})]})])
    style.configure("Vertical.TScrollbar", background=palette.track, troughcolor=palette.surface, bordercolor=palette.surface, lightcolor=palette.track, darkcolor=palette.track, arrowcolor=palette.muted, gripcount=0, width=size(10), arrowsize=size(10))
    style.map("Vertical.TScrollbar", background=[("active", palette.muted)])
    style.configure("Horizontal.TProgressbar", background=palette.accent, troughcolor=palette.track, bordercolor=palette.track, lightcolor=palette.accent, darkcolor=palette.accent, thickness=size(4))
    return scale
