import ctypes
import os
import sys
import uuid

from .paths import long_path

SW_SHOWNORMAL = 1


def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except OSError:
        return False


def can_replace(path):
    probe = os.path.join(os.path.dirname(os.path.abspath(path)), f".mixly-{uuid.uuid4().hex[:8]}")
    try:
        os.mkdir(long_path(probe))
    except OSError:
        return False
    os.rmdir(long_path(probe))
    return True
