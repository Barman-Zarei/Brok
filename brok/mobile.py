"""Phone/tablet entry point (ANDROID and IOS branches).

The desktop avatar is a frameless, translucent, always-on-top window. Mobile operating systems do not allow a normal
app to float above other apps, so the mobile build is a regular full-screen app that opens Brok's **workspace**
(AI chat, project files, diff and approvals) on a private folder inside the app's own storage.

Not available on mobile: global hotkey, desktop tray, X11 activity counters, floating avatar.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from collections.abc import Sequence


def workspace_dir() -> Path:
    """Folder the mobile workspace works in (inside the app's own config/data area)."""
    from . import paths

    d = Path(paths.config_dir()) / "workspace"
    d.mkdir(parents=True, exist_ok=True)
    return d


def main(argv: Sequence[str] | None = None, auto_quit_ms: int = 0) -> int:
    """Start the mobile workspace. ``auto_quit_ms`` is only for tests (quit after N milliseconds)."""
    os.environ.setdefault("BROK_PROFILE", "low-end")
    from . import profile

    profile.apply_environment()
    from PySide6 import QtCore, QtWidgets

    app = QtWidgets.QApplication(list(argv) if argv is not None else sys.argv)
    from .workspace_ui import open_workspace

    win = open_workspace(None, str(workspace_dir()))
    if win is None:
        return 1
    win.showMaximized()
    if auto_quit_ms:
        QtCore.QTimer.singleShot(auto_quit_ms, app.quit)
    return int(app.exec())
