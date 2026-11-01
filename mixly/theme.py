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
