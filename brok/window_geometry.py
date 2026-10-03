"""Screen-position helpers: saved position, clamping to screens, placing pop-ups beside the avatar."""

from __future__ import annotations

import logging

from PySide6 import QtCore, QtGui, QtWidgets

from . import display as _display

logger = logging.getLogger(__name__)


def _m():
    """The ``brok.main`` module, resolved lazily (it imports this module, so a top-level import would be circular)."""
    import importlib

    return importlib.import_module("brok.main")


class GeometryMixin:
    """Screen-position helpers: saved position, clamping to screens, placing pop-ups beside the avatar."""

    def load_position(self) -> None:
        """Load window position from config; default to the bottom-right corner."""
        rect = _display.usable_screen_rect()
        window_width = self.width()
        window_height = self.height()

        config = _m().load_config(rect.width(), rect.height(), window_width, window_height)
        default_x, default_y = self.bottom_right_position(window_width, window_height)
        x = config.get("x", default_x)
        y = config.get("y", default_y)
        x, y = self.clamp_to_screens(x, y, window_width, window_height)
        self.move(x, y)

    def bottom_right_position(self, width: int, height: int) -> tuple[int, int]:
        """Bottom-right corner of the usable screen area (robust to a 0x0 Qt screen)."""
        rect = _display.usable_screen_rect()
        x = rect.x() + rect.width() - width - _m().DEFAULT_POSITION_OFFSET_X
        y = rect.y() + rect.height() - height - _m().DEFAULT_POSITION_OFFSET_Y
        return x, y

    def clamp_to_screens(self, x: int, y: int, width: int, height: int) -> tuple[int, int]:
        """Keep the window visible; robust to Qt reporting empty screen geometry."""
        rect = _display.usable_screen_rect()
        if rect.width() <= 0 or rect.height() <= 0:
            return x, y  # screen size unknown — trust the requested position

        window_rect = QtCore.QRect(x, y, width, height)
        union = QtCore.QRect(rect)
        app = QtWidgets.QApplication.instance()
        for screen in (app.screens() if app is not None else []):
            geo = screen.availableGeometry()
            if geo.width() > 0 and geo.height() > 0:
                union = union.united(geo)
        if union.intersects(window_rect):
            return x, y

        fallback_x = rect.x() + rect.width() - width - _m().DEFAULT_POSITION_OFFSET_X
        fallback_y = rect.y() + rect.height() - height - _m().DEFAULT_POSITION_OFFSET_Y
        logger.warning(
            "Saved position (%d, %d) is off-screen (usable=%s); resetting to (%d, %d)",
            x, y, union, fallback_x, fallback_y,
        )
        return fallback_x, fallback_y
    
    def save_position(self) -> None:
        """Save current window position to config."""
        pos = self.pos()
        config = {"x": pos.x(), "y": pos.y()}
        _m().save_config(config)

    def reset_position(self) -> None:
        """Snap the avatar to the bottom-right corner, an equal inset from each edge.

        Measured from the true screen corner (full geometry, not the
        panel-aware area) so the avatar sits right by the edge. A rescue for when
        it wanders off-screen or gets lost across multiple monitors.
        """
        margin = 18
        screen = QtWidgets.QApplication.primaryScreen()
        rect = screen.geometry() if screen is not None else _display.usable_screen_rect()
        x = rect.x() + rect.width() - self.width() - margin
        y = rect.y() + rect.height() - self.height() - margin
        self.move(x, y)
        self.save_position()

    def cat_body_rect(self) -> QtCore.QRect:
        """Global rect of the drawn (opaque) cat, ignoring the pixmap's transparent
        margins — so pop-ups can sit a few px from the *visible* cat, not the window
        (which is sized to the whole pixmap). Falls back to the window when there's
        no pixmap to scan."""
        frame = self.frameGeometry()
        pixmap = getattr(self, "current_pixmap", None) or getattr(self, "first_frame_pixmap", None)
        if pixmap is None or pixmap.isNull():
            return frame
        image = pixmap.toImage()
        pix_left = max(0, (self.width() - image.width()) // 2)
        pix_top = max(0, (self.height() - image.height()) // 2)
        left, right, top, bottom = image.width(), -1, image.height(), -1
        for row in range(0, image.height(), 2):
            for col in range(0, image.width(), 2):
                if QtGui.qAlpha(image.pixel(col, row)) > 12:
                    left, right = min(left, col), max(right, col)
                    top, bottom = min(top, row), max(bottom, row)
        if right < 0:
            return frame
        origin = self.mapToGlobal(QtCore.QPoint(pix_left + left, pix_top + top))
        return QtCore.QRect(origin.x(), origin.y(), right - left + 1, bottom - top + 1)

    def place_beside_cat(self, dialog) -> None:
        """Open a pop-up beside the avatar, on the side facing the screen centre, so it
        never covers the avatar (or the speech bubble above it).

        Cat on the right half of the screen → the dialog opens to its left; on the
        left half → to its right, flipping over / clamping when a side is tight. It
        opens 5px from the visible cat and stays ≥25px clear of the screen's top and
        bottom, centred vertically on the avatar.
        """
        dialog.adjustSize()
        dw, dh = dialog.width(), dialog.height()
        cat = self.cat_body_rect()
        screen = self.screen() or QtWidgets.QApplication.primaryScreen()
        area = screen.availableGeometry() if screen is not None else cat
        gap, margin = 5, 25
        cat_left, cat_right = cat.left(), cat.right() + 1
        if cat.center().x() >= area.center().x():
            x = cat_left - gap - dw              # cat on the right → open left
        else:
            x = cat_right + gap                  # cat on the left → open right
        if x < area.left():                      # too tight that side → flip over
            x = cat_right + gap
        elif x + dw > area.right():
            x = cat_left - gap - dw
        x = max(area.left(), min(x, area.right() - dw))
        y = cat.center().y() - dh // 2
        y = max(area.top() + margin, min(y, area.bottom() - margin - dh))
        dialog.move(x, y)
