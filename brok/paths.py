"""Single source of truth for Brok's config location.

Config lives in ``~/.config/brok`` on every platform (``Path.home()`` resolves
per-OS). Installs coming from upstream myCat have settings in
``~/.config/mycat``; :func:`migrate_legacy_config` copies them (never moves or
deletes) the first time Brok runs. Data (``activity.db``) and chars use the
per-OS conventional dirs; see ``activity_store.user_data_dir`` /
``char_catalog.user_chars_dir``.
"""

from __future__ import annotations

from pathlib import Path

APP_NAME = "brok"
LEGACY_APP_NAME = "mycat"  # upstream name, read only for one-time migration


def config_dir() -> Path:
    """Directory holding ``config.ini`` (and the LLM history) — ``~/.config/brok``."""
    return Path.home() / ".config" / APP_NAME


def migrate_legacy_config() -> bool:
    """Copy ``~/.config/mycat`` to ``~/.config/brok`` if Brok has no config yet.

    Returns True when a copy happened. The legacy dir is left untouched.
    """
    import shutil

    new, old = config_dir(), Path.home() / ".config" / LEGACY_APP_NAME
    if new.exists() or not old.is_dir():
        return False
    try:
        shutil.copytree(old, new)
    except OSError:
        return False
    return True


def config_file() -> Path:
    """Path to the shared ``config.ini``."""
    return config_dir() / "config.ini"
