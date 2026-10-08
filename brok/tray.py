"""System tray, app icon and Linux desktop-entry installation."""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

from PySide2 import QtCore, QtGui, QtWidgets

from . import autostart, i18n, menu_config, paths, update_check, updater

logger = logging.getLogger(__name__)


def ensure_emoji_font(app) -> None:
    """Give emoji glyphs a fallback so they don't render as tofu boxes on systems
    with no emoji font (common on minimal Linux `pip install`s).

    If the system already has any emoji font (Noto Color Emoji, Segoe UI Emoji,
    Apple Color Emoji, …) this is a no-op, so colour emoji stay colour. Only when
    none is present do we register the bundled monochrome NotoEmoji and add it as
    a fallback on the application font — which flows to every widget and to the
    banners' QFont().
    """
    families = QtGui.QFontDatabase.families()
    if any("emoji" in family.lower() for family in families):
        return
    font_path = Path(__file__).resolve().parent / "assets" / "fonts" / "NotoEmoji-Regular.ttf"
    if not font_path.is_file():
        return
    font_id = QtGui.QFontDatabase.addApplicationFont(str(font_path))
    bundled = QtGui.QFontDatabase.applicationFontFamilies(font_id)
    if not bundled:
        return
    base = app.font()
    base.setFamilies([base.family(), bundled[0]])
    app.setFont(base)
    logger.info("No system emoji font — using the bundled %s fallback", bundled[0])


def tidy_separators(menu: QtWidgets.QMenu) -> None:
    """Drop leading, trailing and doubled separators left after hiding entries."""
    prev_was_separator = True  # treat the top as a separator -> removes a leading one
    for action in menu.actions():
        if action.isSeparator():
            if prev_was_separator:
                menu.removeAction(action)
            else:
                prev_was_separator = True
        else:
            prev_was_separator = False
    trailing = menu.actions()
    if trailing and trailing[-1].isSeparator():
        menu.removeAction(trailing[-1])


def assets_dir() -> Path:
    """The bundled ``brok/assets`` directory.

    main.py is the frozen entry script, so in a PyInstaller onefile its own
    ``__file__`` drops the ``brok/`` prefix (it points at ``<_MEIPASS>/main.py``)
    and a ``__file__``-relative lookup misses the bundled assets — which is why
    the app icon fell back to a drawn 😽 in the Windows exe while skins and plane
    sprites, resolved from their own package modules, kept working. Resolve from
    the PyInstaller extraction root when frozen; from this file's directory
    otherwise.
    """
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "brok" / "assets"
    return Path(__file__).resolve().parent / "assets"


def make_app_icon() -> QtGui.QIcon:
    """The app icon (tray, window, splash): brok/assets/icon.png, falling back
    to a drawn 😽 if the file is missing."""
    icon_path = assets_dir() / "icon.png"
    if icon_path.is_file():
        icon = QtGui.QIcon(str(icon_path))
        if not icon.isNull():
            return icon
    pixmap = QtGui.QPixmap(64, 64)
    pixmap.fill(QtCore.Qt.GlobalColor.transparent)
    painter = QtGui.QPainter(pixmap)
    painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
    font = QtGui.QFont()
    font.setPointSize(40)
    painter.setFont(font)
    painter.drawText(pixmap.rect(), QtCore.Qt.AlignmentFlag.AlignCenter, "😽")
    painter.end()
    return QtGui.QIcon(pixmap)


def desktop_exec_command() -> str:
    """The command a menu launcher should run to start brok, for this install."""
    if getattr(sys, "frozen", False):
        target = os.environ.get("APPIMAGE") or sys.executable
        return f'"{target}"'
    console = shutil.which("brok")
    if console:
        return f'"{console}"'
    # Running from source, not pip-installed: launch main.py by absolute path
    # (its import shim works when run as a script from any working directory).
    return f'"{sys.executable}" "{Path(__file__).resolve()}"'


def desktop_version(path) -> str | None:
    """The brok version recorded in a .desktop entry (``X-brok-version``), or None."""
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("X-brok-version="):
                return line.split("=", 1)[1].strip() or None
    except OSError:
        return None
    return None


def install_desktop_entry() -> None:
    """Keep the Linux applications-menu entry pointing at the newest brok the user
    has launched (git, pip or AppImage), so switching between installs fixes the
    launcher's command and icon. The .deb ships its own system-wide entry.

    The entry is only (re)written when this install is at least as new as whatever
    the menu currently launches, so running an older build never downgrades it.

    A snap ships its own menu entry, and its home directory is the snap's private
    one, so an entry written from inside it would never reach the real menu."""
    if sys.platform != "linux" or updater.install_kind() in ("deb", "snap"):
        return
    share = Path.home() / ".local" / "share"
    user_desktop = share / "applications" / "brok.desktop"
    system_desktop = Path("/usr/share/applications/brok.desktop")
    current = update_check.current_version()
    # A user entry shadows the .deb's system one, so the menu runs whichever the
    # user entry points at; fall back to the .deb's recorded version otherwise.
    best = desktop_version(user_desktop) or desktop_version(system_desktop)
    if best is not None and update_check.parse_version(current) < update_check.parse_version(best):
        return
    source_icon = assets_dir() / "icon.png"
    if not source_icon.is_file():
        return
    # Copy the icon and reference it ABSOLUTELY in Icon= — the themed `Icon=brok`
    # form needs the user icon dir to be a full hicolor theme (index.theme + right
    # size folder) and a refreshed cache, which often isn't there; an absolute
    # path just works.
    #
    # Name the copy after its content hash (icon-<hash>.png). A single stable path
    # overwritten in place is invisible to desktop icon caches (GNOME/KDE keep
    # serving the old bitmap for that path), so an updated app kept showing the
    # old launcher icon. A fresh filename whenever the image changes sidesteps the
    # cache entirely.
    icon_dir = share / "brok"
    try:
        digest = hashlib.sha256(source_icon.read_bytes()).hexdigest()[:12]
        icon_target = icon_dir / f"icon-{digest}.png"
        icon_dir.mkdir(parents=True, exist_ok=True)
        if not icon_target.is_file():
            shutil.copyfile(source_icon, icon_target)
        # Drop older copies (previous hashes and the legacy stable-path icon.png)
        # so the folder does not accumulate stale icons.
        for stale in icon_dir.glob("icon-*.png"):
            if stale != icon_target:
                stale.unlink(missing_ok=True)
        (icon_dir / "icon.png").unlink(missing_ok=True)
        user_desktop.parent.mkdir(parents=True, exist_ok=True)
        user_desktop.write_text(
            "[Desktop Entry]\n"
            "Type=Application\n"
            "Name=Brok\n"
            "GenericName=Desktop pet\n"
            "Comment=A tiny animated desktop pet cat\n"
            f"Exec={desktop_exec_command()}\n"
            f"Icon={icon_target}\n"
            "Terminal=false\n"
            "Categories=Utility;Amusement;\n"
            "Keywords=cat;pet;desktop;\n"
            f"X-brok-version={current}\n",
            encoding="utf-8",
        )
        logger.info("Application-menu entry now points at brok %s (%s)", current, user_desktop)
        if shutil.which("update-desktop-database"):
            subprocess.run(  # noqa: S603
                ["update-desktop-database", str(user_desktop.parent)], check=False, capture_output=True
            )
    except OSError as exc:
        logger.debug("Could not install the application-menu entry: %s", exc)


def setup_tray(app, window):
    """A persistent Brok icon in the system tray with a quick-action menu.

    Returns the tray icon (kept alive by the caller), or None when no system
    tray is available.
    """
    if not QtWidgets.QSystemTrayIcon.isSystemTrayAvailable():
        logger.warning("System tray not available — the cat can't be sent to a tray")
        return None
    # The full-colour app icon, same as the window and taskbar.
    tray = QtWidgets.QSystemTrayIcon(make_app_icon(), app)
    tray.setToolTip("Brok")

    def show_window():
        window.show()
        window.raise_()

    def toggle_window():
        if window.isVisible():
            window.hide()
        else:
            show_window()

    menu = QtWidgets.QMenu(window)

    def populate_tray_menu():
        """Rebuild the tray menu each time it opens, honouring the hidden-entry
        settings and showing the correct Open/Close label."""
        menu.clear()
        visible = menu_config.load_menu_visibility()
        toggle_chat = getattr(window, "toggle_llm_chat", None)
        if callable(toggle_chat) and visible["chat"]:
            menu.addAction(i18n.tr("Chat"), toggle_chat)
        # Same order as the context menu: LLM, Calendar, Reminder, GitHub, Activity.
        if visible["llm"]:
            menu.addAction(i18n.tr("LLM…"), window.open_llm_settings)
        menu.addAction(i18n.tr("Coding Workspace…"), window.open_workspace)
        menu.addAction(i18n.tr("Privacy…"), window.open_privacy)
        if visible["calendar"]:
            menu.addAction(i18n.tr("Calendar…"), window.open_calendar_settings)
        if visible["reminder"]:
            menu.addAction(i18n.tr("Reminder…"), window.open_reminder)
        if visible["github"]:
            menu.addAction(i18n.tr("GitHub…"), window.open_github_settings)
        if visible["activity"]:
            menu.addAction(i18n.tr("Activity…"), window.open_activity_dialog)

        # Settings and Language share one block. Settings is always shown — it's
        # how hidden entries are brought back.
        menu.addSeparator()
        menu.addAction(i18n.tr("Settings…"), window.open_settings)
        # Language picker sits right under Settings.
        menu.addMenu(i18n.build_language_menu(paths.config_file()))
        menu.addSeparator()
        menu.addAction(i18n.tr("Reset"), window.reset_position)
        menu.addAction(i18n.tr("Update…"), window.open_update)
        if autostart.is_supported():
            menu.addSeparator()
            login_action = menu.addAction(i18n.tr("Autostart"))
            login_action.setCheckable(True)
            login_action.setChecked(autostart.is_enabled())
            login_action.toggled.connect(autostart.set_enabled)
        menu.addSeparator()
        # Dynamic label: "Open" when the avatar is hidden, "Close" when on screen.
        toggle_action = menu.addAction(i18n.tr("Close") if window.isVisible() else i18n.tr("Open"))
        toggle_action.triggered.connect(toggle_window)
        menu.addAction(i18n.tr("Quit"), QtWidgets.QApplication.quit)
        tidy_separators(menu)

    populate_tray_menu()
    menu.aboutToShow.connect(populate_tray_menu)
    tray.setContextMenu(menu)

    def on_activated(reason):
        if reason == QtWidgets.QSystemTrayIcon.ActivationReason.DoubleClick:
            show_window()

    tray.activated.connect(on_activated)
    tray.show()
    # Some X11 panels (e.g. XFCE) aren't ready for the tray when we first show it
    # (before the event loop runs), so the icon silently fails to embed. Re-assert
    # it a moment after the loop starts — show() is idempotent.
    QtCore.QTimer.singleShot(1500, tray.show)
    logger.info("Tray icon shown (visible=%s)", tray.isVisible())
    return tray
