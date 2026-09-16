"""Locate read-only application resources in source and PyInstaller builds."""

import os
import sys


_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def resource_path(relative_path):
    """Return an absolute path under the source tree or PyInstaller bundle."""
    base = getattr(sys, "_MEIPASS", _PROJECT_ROOT)
    return os.path.join(base, relative_path)
