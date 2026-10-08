"""Display-server helpers: X11 compositor/screen detection, usable area, virtual monitor."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys

from PySide2 import QtCore, QtWidgets

logger = logging.getLogger(__name__)


def x11_compositor_active() -> bool | None:
    """Return True/False when an X11 compositing manager is running, None if undetermined.

    Every EWMH-compliant compositor (picom, xfwm4, mutter, kwin, ...) owns the
    `_NET_WM_CM_Sn` selection while active. We query that owner via libX11 so the
    check works on any X11 desktop, not just XFCE. Returns None on non-X11
    platforms or when libX11 / the display is unavailable.
    """
    if sys.platform.startswith("win") or sys.platform == "darwin":
        return None
    if not os.environ.get("DISPLAY"):
        return None
    try:
        import ctypes

        x11 = ctypes.CDLL("libX11.so.6")
    except OSError:
        return None

    x11.XOpenDisplay.restype = ctypes.c_void_p
    x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
    x11.XDefaultScreen.restype = ctypes.c_int
    x11.XDefaultScreen.argtypes = [ctypes.c_void_p]
    x11.XInternAtom.restype = ctypes.c_ulong
    x11.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
    x11.XGetSelectionOwner.restype = ctypes.c_ulong
    x11.XGetSelectionOwner.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    x11.XCloseDisplay.argtypes = [ctypes.c_void_p]

    display = x11.XOpenDisplay(None)
    if not display:
        return None
    try:
        screen = x11.XDefaultScreen(display)
        atom = x11.XInternAtom(display, f"_NET_WM_CM_S{screen}".encode(), False)
        return x11.XGetSelectionOwner(display, atom) != 0
    finally:
        x11.XCloseDisplay(display)


def x11_screen_size() -> tuple | None:
    """Root window size straight from the X server, for when Qt reports a 0x0 screen.

    Some X setups (nested or remote servers without RANDR) leave QScreen geometry
    empty even though the display has a real size. libX11's XDisplayWidth/Height
    still return the true dimensions. Returns None off X11 or when unavailable.
    """
    if sys.platform.startswith("win") or sys.platform == "darwin":
        return None
    if not os.environ.get("DISPLAY"):
        return None
    try:
        import ctypes

        x11 = ctypes.CDLL("libX11.so.6")
    except OSError:
        return None

    x11.XOpenDisplay.restype = ctypes.c_void_p
    x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
    x11.XDefaultScreen.restype = ctypes.c_int
    x11.XDefaultScreen.argtypes = [ctypes.c_void_p]
    x11.XDisplayWidth.restype = ctypes.c_int
    x11.XDisplayWidth.argtypes = [ctypes.c_void_p, ctypes.c_int]
    x11.XDisplayHeight.restype = ctypes.c_int
    x11.XDisplayHeight.argtypes = [ctypes.c_void_p, ctypes.c_int]
    x11.XCloseDisplay.argtypes = [ctypes.c_void_p]

    display = x11.XOpenDisplay(None)
    if not display:
        return None
    try:
        screen = x11.XDefaultScreen(display)
        width = x11.XDisplayWidth(display, screen)
        height = x11.XDisplayHeight(display, screen)
        if width > 0 and height > 0:
            return width, height
        return None
    finally:
        x11.XCloseDisplay(display)


def usable_screen_rect() -> QtCore.QRect:
    """Best-effort usable screen rectangle, robust to Qt reporting a 0x0 screen.

    Prefers Qt's panel-aware availableGeometry, then full geometry, then the X
    server's root size (XDisplayWidth/Height). Returns an empty rect only when
    nothing is determinable.
    """
    screen = QtWidgets.QApplication.primaryScreen()
    if screen is not None:
        for rect in (screen.availableGeometry(), screen.geometry()):
            if rect.width() > 0 and rect.height() > 0:
                return rect
    size = x11_screen_size()
    if size is not None:
        return QtCore.QRect(0, 0, size[0], size[1])
    return QtCore.QRect(0, 0, 0, 0)


def randr_monitor_count() -> int | None:
    """Number of active RANDR monitors via `xrandr --listmonitors`, or None if unknown."""
    xrandr = shutil.which("xrandr")
    if not xrandr:
        return None
    try:
        result = subprocess.run(
            [xrandr, "--listmonitors"], capture_output=True, text=True, timeout=5
        )
    except (OSError, subprocess.SubprocessError):
        return None
    for line in result.stdout.splitlines():
        head, sep, rest = line.partition("Monitors:")
        if sep:
            try:
                return int(rest.strip())
            except ValueError:
                return None
    return None


def ensure_virtual_monitor() -> None:
    """Register a virtual RANDR monitor when a headless/VNC X server exposes none.

    Such servers have a real framebuffer but zero active RANDR monitors, so Qt
    reports a 0x0 screen and window positioning plus menu/dialog popups break.
    Adding a monitor spanning the framebuffer makes Qt see the real screen size.
    Must run before the QApplication is created. No-op when a monitor already
    exists, on non-X11 platforms, or when xrandr is unavailable.
    """
    if sys.platform.startswith("win") or sys.platform == "darwin":
        return
    if not os.environ.get("DISPLAY") or os.environ.get("QT_QPA_PLATFORM") == "offscreen":
        return
    count = randr_monitor_count()
    if count is None or count > 0:
        return
    size = x11_screen_size()
    if size is None:
        return
    width, height = size
    mm_width = round(width / 96 * 25.4)
    mm_height = round(height / 96 * 25.4)
    geometry = f"{width}/{mm_width}x{height}/{mm_height}+0+0"
    xrandr = shutil.which("xrandr")
    if not xrandr:
        return
    try:
        subprocess.run(
            [xrandr, "--setmonitor", "brok-virtual", geometry, "none"],
            capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return
    logger.info("No active RANDR monitor — registered virtual monitor %s so Qt sees the screen.", geometry)
