import ctypes
import os
import winreg

from .paths import full, is_within, rebase

REG_SZ = winreg.REG_SZ
HWND_BROADCAST = 0xFFFF
WM_SETTINGCHANGE = 0x1A
SMTO_ABORTIFHUNG = 0x2


class RegistryEnv:
    def __init__(self, subkey="Environment", broadcast=True):
        self.subkey = subkey
        self.should_broadcast = broadcast

    def _open(self, access):
        return winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, self.subkey, 0, access)

    def items(self):
        values = {}
        with self._open(winreg.KEY_READ) as key:
            index = 0
            while True:
                try:
                    name, value, kind = winreg.EnumValue(key, index)
                except OSError:
                    return values
                if kind in (winreg.REG_SZ, winreg.REG_EXPAND_SZ):
                    values[name] = (value, kind)
                index += 1

    def get(self, name):
        try:
            with self._open(winreg.KEY_READ) as key:
                value, kind = winreg.QueryValueEx(key, name)
                return value, kind
        except FileNotFoundError:
            return None

    def set(self, name, value, kind=REG_SZ):
        with self._open(winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, name, 0, kind, value)

    def delete(self, name):
        with self._open(winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, name)

    def broadcast(self):
        if not self.should_broadcast:
            return
        result = ctypes.c_size_t()
        ctypes.windll.user32.SendMessageTimeoutW(
            HWND_BROADCAST, WM_SETTINGCHANGE, 0, "Environment", SMTO_ABORTIFHUNG, 2000, ctypes.byref(result)
        )
