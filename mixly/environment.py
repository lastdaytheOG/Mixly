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


def rewrite_path(value, old_root, new_root):
    entries = []
    changed = False
    for entry in value.split(";"):
        expanded = os.path.expandvars(entry.strip())
        if expanded and os.path.isabs(expanded) and is_within(expanded, old_root):
            entries.append(rebase(expanded, old_root, new_root))
            changed = True
        else:
            entries.append(entry)
    return ";".join(entries), changed


def plan_changes(store, source, target, tool_env=()):
    changes = []
    path_changed = False
    current = store.items()
    for name, (value, kind) in current.items():
        if name.upper() == "PATH":
            continue
        expanded = os.path.expandvars(value)
        if os.path.isabs(expanded) and is_within(expanded, source):
            changes.append({"name": name, "before": [value, kind], "after": rebase(expanded, source, target), "kind": kind})
    named = {change["name"].upper() for change in changes}
    for name in tool_env:
        if name.upper() in named:
            continue
        existing = next((key for key in current if key.upper() == name.upper()), None)
        before = list(current[existing]) if existing else None
        changes.append({"name": existing or name, "before": before, "after": full(target), "kind": before[1] if before else REG_SZ})
    path_entry = next((key for key in current if key.upper() == "PATH"), None)
    if path_entry:
        _, path_changed = rewrite_path(current[path_entry][0], source, target)
    return {"values": changes, "path": path_changed}


def apply_changes(store, plan, source, target):
    for change in plan["values"]:
        store.set(change["name"], change["after"], change["kind"])
    if plan["path"]:
        _rewrite_store_path(store, source, target)
    store.broadcast()


def restore_changes(store, plan, source, target):
    for change in plan["values"]:
        current = store.get(change["name"])
        if current is None or current[0] != change["after"]:
            continue
        if change["before"] is None:
            store.delete(change["name"])
        else:
            store.set(change["name"], change["before"][0], change["before"][1])
    if plan["path"]:
        _rewrite_store_path(store, target, source)
    store.broadcast()


def _rewrite_store_path(store, old_root, new_root):
    current = store.items()
    name = next((key for key in current if key.upper() == "PATH"), None)
    if name is None:
        return
    value, kind = current[name]
    updated, changed = rewrite_path(value, old_root, new_root)
    if changed:
        store.set(name, updated, kind)
