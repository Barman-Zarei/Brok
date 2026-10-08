"""Openers for Brok's secondary windows (AI char, workspace, settings, GitHub, calendar, activity, shop, reminder)."""

from __future__ import annotations

import logging

from PySide2 import QtCore, QtWidgets

from . import (
    char_catalog,
)

logger = logging.getLogger(__name__)


def _m():
    """The ``brok.main`` module, resolved lazily (it imports this module, so a top-level import would be circular)."""
    import importlib

    return importlib.import_module("brok.main")


class DialogsMixin:
    """Openers for Brok's secondary windows (AI char, workspace, settings, GitHub, calendar, shop, reminder)."""

    def open_ai_char(self) -> None:
        """Open the reference-photo generator and select its saved result."""
        try:
            if __package__:
                from .ai_char_ui import AICharDialog
            else:
                import importlib

                AICharDialog = importlib.import_module("brok.ai_char_ui").AICharDialog
            dialog = AICharDialog(self)
            dialog.character_created.connect(self.load_image)
            self.place_beside_cat(dialog)
            dialog.exec()
        except Exception as exc:  # noqa: BLE001 - keep the desktop companion alive
            logger.exception("Failed to open AI character generator")
            QtWidgets.QMessageBox.warning(self, "AI character", str(exc))

    def delete_ai_char(self, char_id: str) -> None:
        """Delete a generated pack locally; this never makes an API request."""
        answer = QtWidgets.QMessageBox.question(
            self,
            "Delete custom character?",
            f'Delete "{char_id}" from this computer? This cannot be undone.',
        )
        if answer != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        was_active = self.file_name == char_id
        if not char_catalog.remove_installed(char_id):
            QtWidgets.QMessageBox.warning(self, "Delete custom character", "The character could not be deleted.")
            return
        self.available_images = char_catalog.scan_all()
        if was_active:
            default = _m().DEFAULT_CHAR
            fallback = default if char_catalog.find_char(default) else next(iter(self.available_images), "")
            if fallback:
                self.load_image(fallback)

    def open_workspace(self) -> None:
        """Open the Brok coding workspace (explorer, editor, AI agent, diff, terminal, git)."""
        try:
            from .workspace_ui import open_workspace

            self._workspace = open_workspace(self)
        except Exception:
            logger.exception("Failed to open the coding workspace")

    def open_privacy(self) -> None:
        """Open the privacy dashboard (provider, local/cloud, data sent, memory, accounts)."""
        try:
            from .privacy_ui import open_privacy

            self._privacy_dialog = open_privacy(self)
        except Exception:
            logger.exception("Failed to open the privacy dashboard")

    def open_llm_settings(self) -> None:
        """Open the LLM vendor settings dialog (vendor, model, test, save)."""
        try:
            if __package__:
                from .llm_settings_ui import LLMSettingsDialog
            else:
                import importlib

                LLMSettingsDialog = importlib.import_module(
                    "brok.llm_settings_ui"
                ).LLMSettingsDialog
        except Exception:
            logger.exception("Failed to import LLM settings dialog")
            return
        dialog = LLMSettingsDialog(self, parent=self)
        self.place_beside_cat(dialog)
        dialog.exec()

    def open_settings(self) -> None:
        """Open the general Settings dialog (wait time + which menu entries show)."""
        try:
            if __package__:
                from .settings_ui import SettingsDialog
            else:
                import importlib

                SettingsDialog = importlib.import_module("brok.settings_ui").SettingsDialog
        except Exception:
            logger.exception("Failed to import Settings dialog")
            return
        dialog = SettingsDialog(self, config_path=_m().CFG_FILE, main_window=self)
        self.place_beside_cat(dialog)
        dialog.exec()

    def open_github_settings(self) -> None:
        """Open the GitHub notifier settings dialog (token, filters, test)."""
        notifier = getattr(self, "github_notifier", None)
        if notifier is None:
            return
        try:
            if __package__:
                from .github_ui import GitHubDialog
            else:
                import importlib
                GitHubDialog = importlib.import_module("brok.github_ui").GitHubDialog
        except Exception:
            logger.exception("Failed to import GitHub settings UI")
            return
        dialog = GitHubDialog(notifier, parent=self)
        self.place_beside_cat(dialog)
        dialog.show()
        dialog.raise_()

    def open_calendar_settings(self) -> None:
        """Open the calendar reminder settings dialog (ICS URL, lead time)."""
        controller = getattr(self, "calendar_controller", None)
        if controller is None:
            return
        try:
            if __package__:
                from .calendar_ui import CalendarDialog
            else:
                import importlib
                CalendarDialog = importlib.import_module("brok.calendar_ui").CalendarDialog
        except Exception:
            logger.exception("Failed to import calendar settings UI")
            return
        dialog = CalendarDialog(controller, parent=self)
        self.place_beside_cat(dialog)
        dialog.show()
        dialog.raise_()

    def open_activity_dialog(self) -> None:
        """Open the activity diary dialog (settings + interval log)."""
        collector = getattr(self, "activity_collector", None)
        if collector is None:
            return
        try:
            if __package__:
                from .activity_ui import ActivityDialog
            else:
                import importlib
                ActivityDialog = importlib.import_module("brok.activity_ui").ActivityDialog
        except Exception:
            logger.exception("Failed to import activity UI")
            return
        dialog = ActivityDialog(collector, focus_controller=getattr(self, "focus_controller", None), parent=self)
        self.place_beside_cat(dialog)
        dialog.show()
        dialog.raise_()

    def open_shop(self) -> None:
        """Lazily import and show the shop dialog."""
        existing = getattr(self, "shop_dialog", None)
        if existing is not None:
            try:
                existing.show()
                existing.raise_()
                existing.activateWindow()
                return
            except RuntimeError:
                self.shop_dialog = None  # Qt object was deleted

        try:
            if __package__:
                from .shop_ui import ShopDialog
            else:
                import importlib
                ShopDialog = importlib.import_module("brok.shop_ui").ShopDialog
        except Exception:
            logger.exception("Failed to import shop UI")
            return

        dialog = ShopDialog(self, config_path=_m().CFG_FILE)
        dialog.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose, True)
        dialog.destroyed.connect(lambda _=None: setattr(self, "shop_dialog", None))
        dialog.char_installed.connect(self.on_char_installed)
        dialog.char_uninstalled.connect(self.on_char_uninstalled)
        self.shop_dialog = dialog
        self.place_beside_cat(dialog)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def open_reminder(self) -> None:
        """Open the reminder settings dialog."""
        controller = getattr(self, "reminder_controller", None)
        if controller is not None:
            controller.open_dialog()
