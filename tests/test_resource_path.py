import os
import sys
from pathlib import Path

from lib.resource_path import resource_path


ROOT = Path(__file__).resolve().parent.parent


def test_resource_path_uses_project_root_during_development(monkeypatch):
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)

    actual = resource_path("res/buttons/banner.png")

    assert actual == os.path.join(str(ROOT), "res/buttons/banner.png")


def test_resource_path_uses_pyinstaller_bundle_root(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)

    actual = resource_path("res/buttons/banner.png")

    assert actual == os.path.join(str(tmp_path), "res/buttons/banner.png")
