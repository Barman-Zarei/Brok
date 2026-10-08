"""Phone/tablet entry point (ANDROID and IOS branches).

The desktop avatar is a frameless, translucent, always-on-top window. Mobile operating systems do not allow a normal
app to float above other apps, so the mobile build is a regular full-screen app that opens Brok's **workspace**
(AI chat, project files, diff and approvals) on a private folder inside the app's own storage.

Not available on mobile: global hotkey, desktop tray, X11 activity counters, floating avatar.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Sequence
from pathlib import Path


def workspace_dir() -> Path:
    """Folder the mobile workspace works in (inside the app's own config/data area)."""
    from . import paths

    d = Path(paths.config_dir()) / "workspace"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _use_app_data_dir_if_home_unwritable(app_name: str = "Brok") -> None:
    """Point the config at Qt's per-app data dir when ``$HOME`` is missing or read-only (common in app sandboxes)."""
    if os.environ.get("BROK_CONFIG_DIR") or os.environ.get("ANDROID_PRIVATE"):
        return
    try:
        home_ok = os.access(Path.home(), os.W_OK)
    except (RuntimeError, OSError):  # Path.home() raises when HOME is unset and there is no passwd entry
        home_ok = False
    if home_ok:
        return
    from PySide6 import QtCore

    QtCore.QCoreApplication.setApplicationName(app_name)
    base = QtCore.QStandardPaths.writableLocation(QtCore.QStandardPaths.StandardLocation.AppDataLocation)
    if base:
        os.environ["BROK_CONFIG_DIR"] = str(Path(base) / "config")


def main(argv: Sequence[str] | None = None, auto_quit_ms: int = 0) -> int:
    """Start the mobile workspace. ``auto_quit_ms`` is only for tests (quit after N milliseconds)."""
    os.environ.setdefault("BROK_PROFILE", "low-end")
    from . import profile

    profile.apply_environment()
    from PySide6 import QtCore, QtWidgets

    app = QtWidgets.QApplication(list(argv) if argv is not None else sys.argv)
    _use_app_data_dir_if_home_unwritable()
    from .workspace_ui import open_workspace

    win = open_workspace(None, str(workspace_dir()))
    if win is None:
        return 1
    win.showMaximized()
    if auto_quit_ms:
        QtCore.QTimer.singleShot(auto_quit_ms, app.quit)
    return int(app.exec())
