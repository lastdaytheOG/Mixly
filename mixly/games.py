import glob
import json
import os
import re
import winreg

from .catalog import Tool

PAIR = re.compile(r'"([^"\\]*(?:\\.[^"\\]*)*)"\s+"([^"\\]*(?:\\.[^"\\]*)*)"')
STEAM = ("steam.exe", "steamwebhelper.exe")
EPIC = ("EpicGamesLauncher.exe",)
GOG = ("GalaxyClient.exe",)
UBISOFT = ("upc.exe", "UbisoftConnect.exe")


def parse_pairs(text):
    return [(key, value.replace("\\\\", "\\")) for key, value in PAIR.findall(text)]


def _read(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            return handle.read()
    except OSError:
        return ""


def _registry_value(hive, key, name):
    try:
        with winreg.OpenKey(hive, key) as entry:
            return winreg.QueryValueEx(entry, name)[0]
    except OSError:
        return None


def _registry_children(hive, key):
    try:
        with winreg.OpenKey(hive, key) as root:
            names = []
            index = 0
            while True:
                try:
                    names.append(winreg.EnumKey(root, index))
                except OSError:
                    return names
                index += 1
    except OSError:
        return []
