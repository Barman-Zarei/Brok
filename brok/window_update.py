"""Self-update flow for the Brok window: version check, download, progress and result handling."""

from __future__ import annotations

import logging
import os
import threading

from PySide6 import QtCore, QtGui, QtWidgets

from . import (
    char_catalog,
    github_api,
    update_check,
    updater,
)

logger = logging.getLogger(__name__)


def _m():
    """The ``brok.main`` module, resolved lazily (it imports this module, so a top-level import would be circular)."""
    import importlib

    return importlib.import_module("brok.main")


class UpdateMixin:
    """Self-update flow for the Brok window: version check, download, progress and result handling."""

    def open_update(self) -> None:
        """Check the latest release; for a frozen build, offer to self-update."""
        kind = updater.install_kind()
        current = update_check.current_version()
        signals = _m().UpdateSignals(self)
        self.update_signals = signals  # keep alive while the flow runs
        signals.checked.connect(lambda latest: self.on_update_checked(kind, current, latest))
        signals.failed.connect(self.on_update_failed)

        def check() -> None:
            # Emit the raw latest tag (or "" when GitHub couldn't be reached) and
            # let on_update_checked decide up-to-date vs. newer vs. check-failed —
            # so a rate-limited/offline check never poses as "you're up to date".
            try:
                signals.checked.emit(update_check.latest_release_tag(token=github_api.github_token()) or "")
            except Exception as exc:  # noqa: BLE001 - surfaced to the user
                signals.failed.emit(str(exc))

        threading.Thread(target=check, name="brok-update-check", daemon=True).start()

    def update_box(self, title: str, text: str, informative: str, kind: str, can_update: bool) -> None:
        """The update dialog — always three buttons: Releases · Update · Close.

        Releases always opens the GitHub releases page. Update downloads the new
        build and restarts, and is enabled only when a self-update is actually
        possible (Windows/macOS with a newer release); it is greyed out on
        pip/git/deb/AppImage installs and whenever there's nothing to update."""
        box = QtWidgets.QMessageBox(self)
        box.setWindowTitle(title)
        box.setText(text)
        box.setInformativeText(informative)
        box.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
        releases_button = box.addButton("Releases", QtWidgets.QMessageBox.ButtonRole.ActionRole)
        update_button = box.addButton("Update", QtWidgets.QMessageBox.ButtonRole.ActionRole)
        update_button.setEnabled(can_update)
        box.addButton(QtWidgets.QMessageBox.StandardButton.Close)
        self.place_beside_cat(box)
        box.exec()
        clicked = box.clickedButton()
        if clicked is releases_button:
            QtGui.QDesktopServices.openUrl(QtCore.QUrl(updater.RELEASES_PAGE))
        elif clicked is update_button:
            self.download_update(kind)

    def on_update_checked(self, kind: str, current: str, latest: str) -> None:
        # One dialog everywhere (Releases · Update · Close). Update is live only
        # in the last case: a reachable, newer release on a self-updating build.
        if not latest:
            # The check couldn't reach GitHub (offline, or the API rate-limited
            # this IP). Don't claim we're up to date — say the check failed.
            self.update_box(
                "Brok",
                f"Current: {current}",
                "Couldn't reach GitHub — try again in a bit.",
                kind,
                can_update=False,
            )
            return
        versions = f"Current: {current}\nLatest: {latest}"
        if update_check.parse_version(latest) <= update_check.parse_version(current):
            # Up to date — nothing to update, so Update stays greyed out.
            self.update_box(
                "Brok",
                versions,
                "No update needed — you're on the latest version. 🤖",
                kind,
                can_update=False,
            )
            return
        if not updater.can_self_update(kind):
            # pip / git / deb / AppImage: tell them how, Update stays greyed out.
            self.update_box(
                "Brok",
                versions,
                f"Update available. Update with:\n\n    {updater.update_hint(kind)}",
                kind,
                can_update=False,
            )
            return
        # Windows / macOS with a newer release: Update is enabled.
        self.update_box(
            "Brok",
            versions,
            "Update available — click Update to download and restart.",
            kind,
            can_update=True,
        )

    def download_update(self, kind: str) -> None:
        signals = self.update_signals
        dialog = QtWidgets.QProgressDialog("Downloading update…", "Cancel", 0, 100, self)
        dialog.setWindowTitle("Updating Brok")
        dialog.setMinimumDuration(0)
        dialog.setAutoClose(False)
        dialog.setAutoReset(False)
        dialog.setValue(0)
        cancelled = threading.Event()
        dialog.canceled.connect(cancelled.set)

        signals.progress.connect(
            lambda done, total: dialog.setValue(int(done * 100 / total) if total else 0)
        )
        signals.applied.connect(lambda: (dialog.setLabelText("Restarting…"), self.finish_update()))
        signals.failed.connect(lambda message: (dialog.close(), self.on_update_failed(message)))

        def worker() -> None:
            try:
                dest = updater.staging_path(kind)

                def progress(done: int, total: int) -> None:
                    if cancelled.is_set():
                        raise RuntimeError("cancelled")
                    signals.progress.emit(done, total)

                updater.download(updater.asset_url(kind), dest, progress)
                if cancelled.is_set():
                    return
                updater.apply_and_relaunch(kind, dest)
                signals.applied.emit()
            except Exception as exc:  # noqa: BLE001 - surfaced to the user
                if not cancelled.is_set():
                    signals.failed.emit(str(exc))

        threading.Thread(target=worker, name="brok-update", daemon=True).start()
        self.place_beside_cat(dialog)
        dialog.exec()

    def finish_update(self) -> None:
        """New build spawned — this process MUST die now so the swapper can see the
        old PID vanish, overwrite the file, and relaunch.

        ``QApplication.quit()`` is not enough: this runs inside the progress dialog's
        modal ``exec()`` nested event loop, which quit() does not break — so the
        process lingered forever and the Windows swapper hung on its wait loop. Flush
        pending state, then hard-exit so the swapper always proceeds."""
        _m().flush_activity_on_quit(self)
        os._exit(0)

    def on_update_failed(self, message: str) -> None:
        logger.warning("Update failed: %s", message)
        QtWidgets.QMessageBox.warning(self, "Update failed", f"Couldn't update: {message}")

    def on_char_installed(self, _char_id: str) -> None:
        self.available_images = char_catalog.scan_all()

    def on_char_uninstalled(self, char_id: str) -> None:
        self.available_images = char_catalog.scan_all()
        if self.file_name == char_id and self.available_images:
            self.load_image(self.available_images[0])
