"""Shared read/write plumbing for the ``~/.config/brok/config.ini`` sections.

Every feature owns its own dataclass and decides which fields map to which keys
(including any legacy-key fallbacks); this module does the identical
``ConfigParser`` dance once instead of once per feature:

- :func:`read_config` — parse the file (or ``None`` if absent/unreadable),
- :func:`write_section` — merge one section back without touching the others,
  create the file, and secure it,
- :func:`bool_str` — serialize a bool the way the config has always stored it.
"""

from __future__ import annotations

import configparser
import locale
import logging
import os
import shutil
from pathlib import Path

from . import secret_store

logger = logging.getLogger(__name__)


def new_parser() -> configparser.ConfigParser:
    """A parser WITHOUT value interpolation.

    The default ``BasicInterpolation`` treats ``%`` specially: saving ``100%`` or a URL-encoded URL raised
    ``ValueError``, and a hand-edited ``%`` made the whole file unreadable (all settings fell back to defaults).
    """
    return configparser.ConfigParser(interpolation=None)


def read_for_update(cfg_file: Path) -> configparser.ConfigParser:
    """The current content as a parser, for a read-modify-write.

    If the file cannot be parsed (hand-edited duplicate option, ...) a copy is kept as ``<name>.corrupt`` BEFORE the
    caller's save replaces it: previously the save silently started from an empty parser, so changing one LLM setting
    destroyed the window position, GitHub token, vendors... of an otherwise recoverable file.
    """
    config = new_parser()
    if cfg_file.exists():
        try:
            config.read_string(read_config_text(cfg_file), source=str(cfg_file))
        except (configparser.Error, OSError) as exc:
            backup = cfg_file.with_name(cfg_file.name + ".corrupt")
            try:
                if not backup.exists():  # keep the FIRST unreadable copy; later saves must not overwrite it
                    shutil.copy2(cfg_file, backup)
                logger.warning("%s unreadable (%s); copy kept as %s, starting a new file", cfg_file, exc, backup)
            except OSError:
                pass
            config = new_parser()
    return config


def write_config(cfg_file: Path, config: configparser.ConfigParser) -> None:
    """Write ``config`` to ``cfg_file`` atomically and owner-only from the first byte.

    A temp file is created with mode 600 (no window where plaintext secrets are world-readable), flushed to disk, then
    renamed over the target. A crash or full disk therefore leaves the previous file intact instead of a truncated one.
    """
    tmp = cfg_file.with_name(cfg_file.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            config.write(fh)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, cfg_file)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    secret_store.secure_file(cfg_file)


def bool_str(value: bool) -> str:
    """``True``/``False`` -> the ``"true"``/``"false"`` the config stores."""
    return "true" if value else "false"


def read_config_text(cfg_file: Path) -> str:
    """``cfg_file`` as text: UTF-8, or the machine's locale codec if that is what wrote it.

    The fallback is the upgrade path, not a guess. Before this project named an encoding, the
    file was written in whatever codec the locale supplied, so an existing config on a
    cp1252/cp949/gbk Windows install is not UTF-8 -- and reading it as UTF-8 raises
    ``UnicodeDecodeError`` where callers catch only ``configparser.Error``. Every writer names
    UTF-8, so the first save after this rewrites the file clean and the fallback stops firing.
    """
    try:
        return cfg_file.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        codec = locale.getpreferredencoding(False)
        text = cfg_file.read_text(encoding=codec, errors="replace")
        logger.warning(
            "%s is not UTF-8; read with locale codec %s and will be rewritten as UTF-8 on next save",
            cfg_file,
            codec,
        )
        return text


def read_config(cfg_file: Path) -> configparser.ConfigParser | None:
    """Parse ``cfg_file``, or ``None`` if it is absent or cannot be read."""
    if not cfg_file.exists():
        return None
    config = new_parser()
    try:
        config.read_string(read_config_text(cfg_file), source=str(cfg_file))
    except (configparser.Error, OSError) as exc:
        logger.error("Failed to read %s: %s", cfg_file, exc)
        return None
    return config


def write_section(name: str, values: dict, cfg_file: Path) -> None:
    """Merge ``values`` into the ``[name]`` section of ``cfg_file``.

    Creates the file and the section as needed and leaves every other section
    untouched, then secures the file. Persistence is best-effort: failures are
    logged, never raised.
    """
    try:
        cfg_file.parent.mkdir(parents=True, exist_ok=True)
        config = read_for_update(cfg_file)  # an unparsable file is backed up, not a permanent save blocker
        if name not in config:
            config.add_section(name)
        config[name].update({key: str(value) for key, value in values.items()})
        write_config(cfg_file, config)
    except (OSError, configparser.Error) as exc:
        logger.error("Failed to save [%s] to %s: %s", name, cfg_file, exc)


def remove_section(name: str, cfg_file: Path) -> None:
    """Drop the whole ``[name]`` section from ``cfg_file`` (no-op if absent)."""
    try:
        if not cfg_file.exists():
            return
        config = new_parser()
        config.read_string(read_config_text(cfg_file), source=str(cfg_file))
        if config.remove_section(name):
            write_config(cfg_file, config)
    except (OSError, configparser.Error) as exc:
        logger.error("Failed to clear [%s] in %s: %s", name, cfg_file, exc)
