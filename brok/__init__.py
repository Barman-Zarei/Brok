from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("brok")
except PackageNotFoundError:
    __version__ = "0.0.0"

from . import qt5compat as _qt5compat  # noqa: E402

_qt5compat.install()  # PySide2 stands in for PySide6 on Windows 7 (no-op elsewhere)

__all__ = ["__version__"]
