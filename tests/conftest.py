"""Shared pytest fixtures. Qt runs headless via the offscreen platform."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# isort: off
import brok  # noqa: F401,E402  (installs the PySide2 alias; must come before the first PySide6 import)
import pytest  # noqa: E402
from PySide2 import QtWidgets  # noqa: E402
# isort: on


@pytest.fixture(scope="session")
def qapp():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield app
