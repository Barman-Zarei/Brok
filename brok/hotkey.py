"""Configurable global hotkey (e.g. ``ctrl+space``). Works where pynput can; otherwise reports why not."""

from __future__ import annotations

import logging
from typing import Callable

logger = logging.getLogger(__name__)
_SPECIAL = {"ctrl", "alt", "shift", "cmd", "space", "enter", "tab", "esc"}


def to_pynput(combo: str) -> str:
    """``'ctrl+space'`` → ``'<ctrl>+<space>'``; raises ValueError for empty/invalid combos."""
    keys = [k.strip().lower() for k in combo.split("+") if k.strip()]
    if len(keys) < 2:
        raise ValueError("hotkey needs a modifier plus a key, e.g. ctrl+space")
    if keys[-1] in ("ctrl", "alt", "shift", "cmd"):
        raise ValueError("hotkey must end with a non-modifier key")
    return "+".join(f"<{k}>" if k in _SPECIAL or (k.startswith("f") and k[1:].isdigit()) else k for k in keys)


class HotkeyManager:
    def __init__(self, combo: str, callback: Callable[[], None]) -> None:
        self.combo, self.callback = combo, callback
        self._listener: object | None = None
        self.status = "stopped"

    def start(self) -> bool:
        try:
            spec = to_pynput(self.combo)
        except ValueError as exc:
            self.status = f"invalid hotkey: {exc}"
            return False
        try:
            from pynput import keyboard  # type: ignore

            self._listener = keyboard.GlobalHotKeys({spec: self.callback})
            self._listener.start()  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001 - optional feature must never crash the app
            self.status = f"unavailable on this system ({type(exc).__name__}); use the tray icon instead"
            logger.warning("global hotkey unavailable: %s", exc)
            return False
        self.status = "active"
        return True

    def stop(self) -> None:
        if self._listener is not None:
            try:
                self._listener.stop()  # type: ignore[attr-defined]
            except Exception:  # noqa: BLE001
                pass
        self._listener, self.status = None, "stopped"
