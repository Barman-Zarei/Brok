from __future__ import annotations

from typing import Dict

THEMES: Dict[str, Dict[str, str]] = {
    "cyan": {"body": "#3b4a63", "panel": "#243044", "accent": "#35e0ff", "glow": "#9cf3ff", "warn": "#ffb020",
             "error": "#ff4d5e", "ok": "#3ddc84", "line": "#141b29"},
    "violet": {"body": "#4a3b63", "panel": "#2c2444", "accent": "#b57bff", "glow": "#dcc2ff", "warn": "#ffb020",
               "error": "#ff4d5e", "ok": "#3ddc84", "line": "#1a1429"},
    "amber": {"body": "#5e5440", "panel": "#3a3224", "accent": "#ffc245", "glow": "#ffe3a1", "warn": "#ff8a3d",
              "error": "#ff4d5e", "ok": "#3ddc84", "line": "#201a10"},
}


def get_theme(name: str) -> Dict[str, str]:
    return THEMES.get(name, THEMES["cyan"])
