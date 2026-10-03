"""Qt glue for the global hotkey: the listener thread only emits a signal; the GUI thread does the work."""

from __future__ import annotations

import logging
from typing import Any

from PySide6 import QtCore

from .hotkey import HotkeyManager

logger = logging.getLogger(__name__)


class HotkeyBridge(QtCore.QObject):
    triggered = QtCore.Signal()

    def __init__(self, window: Any, combo: str) -> None:
        super().__init__()
        self.window = window
        self.triggered.connect(self.show_brok)  # queued: runs in the GUI thread
        self.manager = HotkeyManager(combo, self.triggered.emit)

    def show_brok(self) -> None:
        """Bring Brok up and open the chat (or just raise the avatar if chat is unavailable)."""
        w = self.window
        w.show()
        w.raise_()
        toggle = getattr(w, "toggle_llm_chat", None)
        if callable(toggle):
            toggle()

    def start(self) -> bool:
        ok = self.manager.start()
        logger.info("Global hotkey %s: %s", self.manager.combo, self.manager.status)
        return ok


def start_hotkey(window: Any, combo: str = "") -> HotkeyBridge:
    from .config import BrokConfig

    bridge = HotkeyBridge(window, combo or BrokConfig.load().ui.hotkey)
    bridge.start()
    return bridge
