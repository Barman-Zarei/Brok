"""Qt 5 (PySide2) compatibility layer for the WIN7 branch.

Windows 7 cannot run Qt 6/PySide6, but it can run Qt 5.15/PySide2 on Python 3.8. All of Brok is written against
PySide6, so on machines where PySide6 is missing and PySide2 is present this module registers PySide2 under the
``PySide6`` name and adds the few Qt 6 APIs Brok uses that Qt 5 lacks:

* ``QtGui.QAction`` / ``QShortcut`` / ``QActionGroup`` (they live in QtWidgets in Qt 5),
* ``exec()`` on QApplication/QDialog/QMenu/QEventLoop (Qt 5 only has ``exec_()``),
* ``QMouseEvent.position()`` / ``globalPosition()`` (Qt 5 has ``localPos()`` / ``screenPos()``),
* ``QFontDatabase.families()`` as a static call (an instance method in Qt 5).

Scoped enums (``Qt.AlignmentFlag.AlignCenter``) already work in PySide2 5.15. If PySide6 is importable this module
does nothing, so the same code runs unchanged on every other platform.
"""

from __future__ import annotations

import importlib.util
import sys


def install() -> bool:
    """Alias PySide2 as PySide6 when needed. Returns True if the alias was installed."""
    if "PySide6" in sys.modules or importlib.util.find_spec("PySide6") is not None:
        return False
    if importlib.util.find_spec("PySide2") is None:
        return False  # neither is installed: let the normal ImportError explain it
    import PySide2
    from PySide2 import QtCore, QtGui, QtNetwork, QtWidgets

    for name in ("QAction", "QShortcut", "QActionGroup"):
        if not hasattr(QtGui, name) and hasattr(QtWidgets, name):
            setattr(QtGui, name, getattr(QtWidgets, name))
    for cls in (QtWidgets.QApplication, QtWidgets.QDialog, QtWidgets.QMenu, QtCore.QEventLoop, QtCore.QCoreApplication):
        if not hasattr(cls, "exec") and hasattr(cls, "exec_"):
            cls.exec = cls.exec_  # type: ignore[attr-defined]
    for cls in (QtGui.QMouseEvent, QtGui.QWheelEvent):
        if not hasattr(cls, "position"):
            cls.position = lambda self: self.localPos()  # type: ignore[attr-defined]
        if not hasattr(cls, "globalPosition"):
            cls.globalPosition = lambda self: self.screenPos()  # type: ignore[attr-defined]

    module = type(sys)("PySide6")
    font_families = QtGui.QFontDatabase.families

    def _families(*args):  # type: ignore[no-untyped-def]
        # Qt 5 aborts when a QFontDatabase is built before the QGuiApplication exists; Qt 6 returns a list.
        if QtGui.QGuiApplication.instance() is None:
            return []
        return font_families(QtGui.QFontDatabase(), *args)

    QtGui.QFontDatabase.families = staticmethod(_families)  # type: ignore[assignment]

    submodules = {"QtCore": QtCore, "QtGui": QtGui, "QtWidgets": QtWidgets, "QtNetwork": QtNetwork}
    module.__dict__.update(__version__=PySide2.__version__, **submodules)
    sys.modules["PySide6"] = module
    for name, mod in submodules.items():
        sys.modules["PySide6." + name] = mod
    return True
