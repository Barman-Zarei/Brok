"""Shared pytest fixtures. Qt runs headless via the offscreen platform."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6 import QtWidgets  # noqa: E402

import brok  # noqa: F401  (installs the PySide2 alias before PySide6 is imported)


@pytest.fixture(scope="session")
def qapp():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield app
