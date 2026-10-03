"""Privacy dashboard window: what Brok is doing right now (provider, local/cloud, data sent, memory, accounts)."""

from __future__ import annotations

from PySide6 import QtCore, QtWidgets

from .config import BrokConfig
from .i18n import tr
from .privacy import build_report, format_report, get_tracker


class PrivacyDialog(QtWidgets.QDialog):
    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Privacy dashboard"))
        self.resize(520, 460)
        lay = QtWidgets.QVBoxLayout(self)
        self.badge = QtWidgets.QLabel()
        self.badge.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.badge)
        self.body = QtWidgets.QPlainTextEdit()
        self.body.setReadOnly(True)
        lay.addWidget(self.body, 1)
        row = QtWidgets.QHBoxLayout()
        self.refresh_btn = QtWidgets.QPushButton(tr("Refresh"))
        self.refresh_btn.clicked.connect(self.refresh)
        self.close_btn = QtWidgets.QPushButton(tr("Close"))
        self.close_btn.clicked.connect(self.close)
        row.addWidget(self.refresh_btn)
        row.addStretch(1)
        row.addWidget(self.close_btn)
        lay.addLayout(row)
        self.refresh()

    def refresh(self) -> None:
        rep = build_report(BrokConfig.load(), get_tracker())
        cloud = rep.mode == "CLOUD AI"
        self.badge.setText(f"{rep.mode}{'  (offline mode)' if rep.offline else ''}")
        colour = "#b45309" if cloud else "#15803d"
        self.badge.setStyleSheet(f"font-weight:bold;padding:6px;border-radius:6px;color:white;background:{colour};")
        self.body.setPlainText(format_report(rep))


def open_privacy(parent: QtWidgets.QWidget | None = None) -> PrivacyDialog:
    dlg = PrivacyDialog(parent)
    dlg.show()
    return dlg
