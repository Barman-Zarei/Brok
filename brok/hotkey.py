"""Configurable global hotkey (e.g. ``ctrl+space``). Works where pynput can; otherwise reports why not."""

from __future__ import annotations

import logging
from typing import Any, Callable

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
        self._listener: Any = None
        self.status = "stopped"

    def start(self) -> bool:
        try:
            spec = to_pynput(self.combo)
        except ValueError as exc:
            self.status = f"invalid hotkey: {exc}"
            return False
        try:
            from pynput import keyboard

            listener = keyboard.GlobalHotKeys({spec: self.callback})
            listener.start()
            self._listener = listener
        except Exception as exc:  # noqa: BLE001 - optional feature must never crash the app
            hint = " — install it with: pip install \"brok[hotkey]\"" if isinstance(exc, ImportError) else ""
            self.status = f"unavailable on this system ({type(exc).__name__}){hint}; use the tray icon instead"
            logger.warning("global hotkey unavailable: %s", exc)
            return False
        self.status = "active"
        return True

    def stop(self) -> None:
        if self._listener is not None:
            try:
                self._listener.stop()
            except Exception:  # noqa: BLE001
                pass
        self._listener, self.status = None, "stopped"
