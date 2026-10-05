#!/usr/bin/env python3
"""
Brok desktop overlay with GIF animation from ZIP archives, PySide6 transparent overlay
- Shows first frame of GIF from ZIP for 5 seconds, then plays GIF once, then back to first frame
- Shows a frameless, draggable, always-on-top transparent window.
- Right click → Quit.

Dependencies:
pip install PySide6
"""

from __future__ import annotations

import argparse
import configparser
import getpass
import logging
import math
import os
import random
import signal
import sys
import warnings
import zipfile
from pathlib import Path

# Allow running both as `python -m brok` and `python brok/main.py`
if __package__:
    from . import (
        activity,
        announcer,
        autostart,
        calendar_ics,
        char_catalog,
        char_pack,
        config_store,
        digest,
        focus,
        github_api,
        github_notify,
        i18n,
        llm,
        menu_config,
        paths,
        reminder,
        secret_store,
        update_check,
        updater,
    )
else:
    import importlib
    repo_root = Path(__file__).resolve().parent.parent
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    i18n = importlib.import_module("brok.i18n")
    llm = importlib.import_module("brok.llm")
    menu_config = importlib.import_module("brok.menu_config")
    paths = importlib.import_module("brok.paths")
    char_catalog = importlib.import_module("brok.char_catalog")
    reminder = importlib.import_module("brok.reminder")
    secret_store = importlib.import_module("brok.secret_store")
    config_store = importlib.import_module("brok.config_store")
    autostart = importlib.import_module("brok.autostart")
    char_pack = importlib.import_module("brok.char_pack")
    announcer = importlib.import_module("brok.announcer")
    focus = importlib.import_module("brok.focus")
    github_api = importlib.import_module("brok.github_api")
    github_notify = importlib.import_module("brok.github_notify")
    calendar_ics = importlib.import_module("brok.calendar_ics")
    activity = importlib.import_module("brok.activity")
    digest = importlib.import_module("brok.digest")
    update_check = importlib.import_module("brok.update_check")
    updater = importlib.import_module("brok.updater")

from PySide6 import QtCore, QtGui, QtWidgets

from brok.display import (  # noqa: E402,F401
    ensure_virtual_monitor,
    randr_monitor_count,
    usable_screen_rect,
    x11_compositor_active,
    x11_screen_size,
)
from brok.gif_utils import (  # noqa: E402,F401
    get_gif_duration,
    harden_pixmap,
    movie_from_gif_bytes,
    parse_gif_frame_delays,
    scale_pixmap_if_needed,
)
from brok.instance import activate_running_instance, install_macos_reopen, start_activation_server  # noqa: E402,F401
from brok.tray import (  # noqa: E402,F401
    assets_dir,
    desktop_exec_command,
    desktop_version,
    ensure_emoji_font,
    install_desktop_entry,
    make_app_icon,
    setup_tray,
    tidy_separators,
)
from brok.window_dialogs import DialogsMixin  # noqa: E402
from brok.window_geometry import GeometryMixin  # noqa: E402
from brok.window_update import UpdateMixin  # noqa: E402

# Make logs readable for non-ASCII text (Cyrillic, emoji): force UTF-8 on the
# console streams when the locale left them as ASCII (otherwise the logger
# escapes e.g. "Ты" to "Ты").
for console_stream in (sys.stdout, sys.stderr):
    try:
        console_stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

# Configure logging
LOGGING = {
    "handlers": [logging.StreamHandler()],
    "format": "%(asctime)s.%(msecs)03d [%(levelname)s]: (%(name)s) %(message)s",
    "level": logging.INFO,
    "datefmt": "%Y-%m-%d %H:%M:%S",
}
logging.basicConfig(**LOGGING)
logger = logging.getLogger(__name__)
logger.debug("LLM integration module path: %s", getattr(llm, "__file__", "builtin"))

# Bundled default character: the Brok robot (the legacy "cat" char stays available in the Chars menu).
DEFAULT_CHAR = "robot"

# Config paths — single source of truth in paths.py (stays ~/.config/brok).
CFG_DIR = paths.config_dir()
CFG_FILE = paths.config_file()

# Per-user local-socket name: a second `brok` launch uses it to raise the
# running Brok window (so hiding it to a flaky tray is always recoverable).
SINGLE_INSTANCE_NAME = f"brok-{getpass.getuser()}"

# Image scaling settings
IMAGE_WIDTH_MAX = 300  # Maximum width for images in pixels (images will be scaled down if larger)
IMAGE_HEIGHT_MAX = 500  # Maximum height for images in pixels (images will be scaled down if larger)
STATIC_TIME = 5.0  # Seconds to show static first frame before playing GIF

# Window position settings
DEFAULT_POSITION_OFFSET_X = 10  # Offset from right edge of screen
DEFAULT_POSITION_OFFSET_Y = 10  # Offset from bottom edge of screen


def scan_chars() -> list[str]:
    """Return sorted unique char ids from bundled + user-installed locations."""
    return char_catalog.scan_all()










def load_packaged_images(
    image_path: str | None = None, default_image: str | None = None
) -> tuple[QtGui.QPixmap, QtGui.QMovie, str, bytes]:
    """
    Load the GIF from a ZIP archive entirely in memory (no temp files).
    If image_path is provided, use it (should point to a ZIP file).
    Returns: (first_frame_pixmap, gif_movie, base_name, gif_bytes)
    """
    if image_path:
        char_path = Path(image_path)
        if not char_path.exists():
            raise FileNotFoundError(f"Char not found: {char_path}")
    else:
        base_name = default_image or DEFAULT_CHAR
        resolved = char_catalog.find_char(base_name)
        if resolved is None:
            raise FileNotFoundError(f"Char '{base_name}' not found in bundled or user chars dir")
        char_path = resolved
    base_name = char_path.stem

    # Read the first GIF from the char (folder or zip, in memory).
    try:
        with char_pack.CharSource(char_path) as source:
            gif_files = sorted(n for n in source.names() if n.lower().endswith(".gif"))
            if not gif_files:
                raise ValueError(f"No GIF file found in char: {char_path}")
            gif_file_name = gif_files[0]
            gif_data = source.read(gif_file_name)
            logger.info(f"Extracted {gif_file_name} from {char_path.name}")
    except zipfile.BadZipFile as exc:
        raise ValueError(f"Invalid char archive: {char_path}") from exc
    
    # Build the animated movie straight from the GIF bytes in memory.
    movie = movie_from_gif_bytes(gif_data)
    movie.jumpToFrame(0)
    first_frame = movie.currentPixmap()
    if first_frame.isNull():
        raise ValueError(f"Failed to extract first frame from GIF in char: {char_path}")

    # Scale if needed
    original_size = first_frame.size()
    pixmap = scale_pixmap_if_needed(first_frame, IMAGE_WIDTH_MAX, IMAGE_HEIGHT_MAX)
    if original_size != pixmap.size():
        logger.info(
            f"Resized {char_path.name}: "
            f"{original_size.width()}x{original_size.height()} -> "
            f"{pixmap.width()}x{pixmap.height()}"
        )
    if pixmap.isNull():
        raise ValueError(f"Failed to render first frame from GIF in char: {char_path}")

    # Scale GIF movie to same size as the first frame
    movie.setScaledSize(pixmap.size())
    movie.jumpToFrame(0)

    return pixmap, movie, base_name, gif_data


def load_config(screen_width: int, screen_height: int, window_width: int, window_height: int) -> dict:
    """Load configuration from INI file. Returns position for bottom-right corner."""
    # Calculate default position (bottom-right with offset)
    default_x = screen_width - window_width - DEFAULT_POSITION_OFFSET_X
    default_y = screen_height - window_height - DEFAULT_POSITION_OFFSET_Y
    config_data = {'x': default_x, 'y': default_y}
    
    if not CFG_FILE.exists():
        return config_data
    
    try:
        config = configparser.ConfigParser()
        config.read_string(config_store.read_config_text(CFG_FILE), source=str(CFG_FILE))
        
        if 'window' in config:
            if 'x' in config['window']:
                config_data['x'] = int(config['window']['x'])
            if 'y' in config['window']:
                config_data['y'] = int(config['window']['y'])
    except Exception as e:
        logger.error(f"Config load error: {e}")
    
    return config_data


def save_config(config: dict) -> None:
    """Save configuration to INI file."""
    try:
        CFG_DIR.mkdir(parents=True, exist_ok=True)
        
        # Read existing config if it exists
        file_config = configparser.ConfigParser()
        if CFG_FILE.exists():
            file_config.read_string(config_store.read_config_text(CFG_FILE), source=str(CFG_FILE))
        
        # Ensure [window] section exists
        if 'window' not in file_config:
            file_config.add_section('window')
        
        # Update window position if provided
        if 'x' in config:
            file_config['window']['x'] = str(config['x'])
        if 'y' in config:
            file_config['window']['y'] = str(config['y'])
        
        # Write to file
        with open(CFG_FILE, 'w', encoding="utf-8") as f:
            file_config.write(f)
        secret_store.secure_file(CFG_FILE)
    except Exception as e:
        logger.error(f"Config save error: {e}")


def load_image_from_ini() -> str | None:
    """Load default image setting from INI file."""
    if not CFG_FILE.exists():
        logger.info("INI config not found, using default image")
        return None
    
    try:
        config = configparser.ConfigParser()
        config.read_string(config_store.read_config_text(CFG_FILE), source=str(CFG_FILE))
        
        if 'settings' in config and 'default_image' in config['settings']:
            image_name = config['settings']['default_image']
            logger.info(f"Loaded image from INI: {image_name}")
            return image_name
        else:
            logger.info("INI config exists but no default_image setting found, using default image")
            return None
    except Exception as e:
        logger.error(f"Error reading INI file: {e}, using default image")
        return None


def save_image_to_ini(image_name: str) -> None:
    """Save current image setting to INI file (skips writing if value is unchanged)."""
    try:
        CFG_DIR.mkdir(parents=True, exist_ok=True)

        config = configparser.ConfigParser()

        # Read existing config if it exists
        if CFG_FILE.exists():
            config.read_string(config_store.read_config_text(CFG_FILE), source=str(CFG_FILE))

        if (
            config.has_section('settings')
            and config.get('settings', 'default_image', fallback=None) == image_name
        ):
            return

        # Ensure [settings] section exists
        if 'settings' not in config:
            config.add_section('settings')

        # Set the default_image value
        config['settings']['default_image'] = image_name

        # Write to file
        with open(CFG_FILE, 'w', encoding="utf-8") as f:
            config.write(f)
        secret_store.secure_file(CFG_FILE)

        logger.info(f"Saved image setting to INI: {image_name}")
    except Exception as e:
        logger.error(f"Error saving to INI file: {e}")


def autostart_was_prompted() -> bool:
    """Whether the first-run "start on login?" prompt has already been shown.

    Stored as ``[settings] autostart_prompted`` so the user is asked at most once.
    """
    if not CFG_FILE.exists():
        return False
    try:
        config = configparser.ConfigParser()
        config.read_string(config_store.read_config_text(CFG_FILE), source=str(CFG_FILE))
        return config.getboolean("settings", "autostart_prompted", fallback=False)
    except Exception as exc:
        logger.debug("Could not read autostart_prompted flag: %s", exc)
        return False


def mark_autostart_prompted() -> None:
    """Record that the first-run autostart prompt has been shown."""
    try:
        CFG_DIR.mkdir(parents=True, exist_ok=True)
        config = configparser.ConfigParser()
        if CFG_FILE.exists():
            config.read_string(config_store.read_config_text(CFG_FILE), source=str(CFG_FILE))
        if "settings" not in config:
            config.add_section("settings")
        config["settings"]["autostart_prompted"] = "true"
        with open(CFG_FILE, "w", encoding="utf-8") as f:
            config.write(f)
        secret_store.secure_file(CFG_FILE)
    except Exception as exc:
        logger.error("Could not save autostart_prompted flag: %s", exc)


def should_offer_autostart() -> bool:
    """First run, on a platform that supports autostart, not enabled, not asked."""
    return (
        autostart.is_supported()
        and not autostart.is_enabled()
        and not autostart_was_prompted()
    )


def offer_autostart_on_first_run(window: QtWidgets.QWidget) -> None:
    """Ask once, on first run, whether to keep brok on screen every login.

    The whole point of autostart is to make Brok persistent — but the toggle
    is buried in the right-click menu, so most users never find it. A single
    gentle first-run prompt is the biggest lever for "always running".
    """
    if not should_offer_autostart():
        return
    # Record first so a crash mid-prompt never re-asks on every launch.
    mark_autostart_prompted()
    answer = QtWidgets.QMessageBox.question(
        window,
        "brok",
        "Keep brok on screen every time you log in?\n\n"
        "You can change this any time from the right-click menu → Autostart.",
        QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
        QtWidgets.QMessageBox.StandardButton.Yes,
    )
    if answer == QtWidgets.QMessageBox.StandardButton.Yes:
        autostart.set_enabled(True)
        logger.info("Autostart enabled via first-run prompt")


def flush_activity_on_quit(window: QtWidgets.QWidget) -> None:
    """On a clean Quit, flush the current activity minute to the database."""
    collector = getattr(window, "activity_collector", None)
    if collector is not None:
        try:
            collector.flush()
        except Exception as exc:  # noqa: BLE001 - shutdown must never raise
            logger.debug("Activity flush on quit failed: %s", exc)


def read_battery_percent():
    """Battery charge 0–100, or None if there is no battery / can't read it.

    Native Linux /sys first; optional psutil fallback. Used by the 'hungry'
    state — on a desktop with no battery it returns None (state never triggers)."""
    base = Path("/sys/class/power_supply")
    try:
        for entry in base.iterdir():
            try:
                if (entry / "type").read_text(encoding="utf-8").strip() == "Battery":
                    return int((entry / "capacity").read_text(encoding="utf-8").strip())
            except OSError:
                continue
    except OSError:
        pass
    try:
        import psutil
        battery = psutil.sensors_battery()
        if battery is not None:
            return int(battery.percent)
    except Exception:
        pass
    return None




class UpdateSignals(QtCore.QObject):
    """Marshals the self-update worker threads back onto the GUI thread."""

    checked = QtCore.Signal(str)          # latest release tag, or "" if the check couldn't reach GitHub
    progress = QtCore.Signal(int, int)    # bytes done, total (0 = unknown)
    applied = QtCore.Signal()             # new build swapped in + spawned
    failed = QtCore.Signal(str)           # error message


class BrokWindow(DialogsMixin, UpdateMixin, GeometryMixin, QtWidgets.QWidget):
    """Main Brok avatar window widget with PNG/GIF animation and dragging."""
    
    def __init__(
        self,
        png_pixmap: QtGui.QPixmap,
        gif_movie: QtGui.QMovie,
        wait_time: float,
        file_name: str = DEFAULT_CHAR,
        available_images: list[str] = None,
        gif_data: bytes = b"",
        pack: char_pack.CharPack | None = None,
    ) -> None:
        platform_name = ""
        app_instance = QtWidgets.QApplication.instance()
        if app_instance is not None:
            platform_name = (app_instance.platformName() or "").lower()
        
        # Window flags for transparent, frameless, always-on-top window
        # Qt.Window (not Qt.Tool) so Brok gets an entry in the taskbar /
        # program list at startup — Tool windows are hidden from it.
        flags = (
            QtCore.Qt.WindowType.FramelessWindowHint |
            QtCore.Qt.WindowType.Window
        )
        if platform_name != "offscreen":
            flags |= QtCore.Qt.WindowType.WindowStaysOnTopHint
        super().__init__(None, flags)

        # Setup transparency
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setWindowTitle("Brok")
        self.setWindowIcon(make_app_icon())
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)

        # On X11 without a compositor, per-pixel alpha renders as a black box.
        # Fall back to clipping the window to the image silhouette (setMask) so
        # transparency works without a compositor — important for remote desktops
        # where enabling compositing adds noticeable latency. Edges are hard
        # (1-bit), which suits the pixel-art avatar. BROK_SHAPE_MASK=1/0 forces it.
        self.shape_mask_key = None
        force_mask = os.environ.get("BROK_SHAPE_MASK")
        if force_mask in ("0", "1"):
            self.shape_mask_enabled = force_mask == "1"
        else:
            self.shape_mask_enabled = platform_name == "xcb" and x11_compositor_active() is False
        if self.shape_mask_enabled:
            logger.warning(
                "No X11 compositor detected — switching to alternative transparency mode "
                "(shape mask: window clipped to the image silhouette, hard 1-bit edges, no smooth alpha). "
                "Enable display compositing for smooth edges, or force this mode with BROK_SHAPE_MASK=1."
            )

        # Common content fields
        self.wait_time = wait_time
        self.file_name = file_name
        self.available_images = available_images or []
        self.char_pack = pack

        # Content setup branches by char type; the chrome below is shared.
        if self.char_pack is not None:
            self.setup_pack_content()
        else:
            self.setup_gif_content(png_pixmap, gif_movie, gif_data)

        # Dragging state
        self.dragging = False
        self.drag_start_pos = QtCore.QPoint()

        # Set window size to pixmap size (pack: bounding box over all frames).
        self.resize(self.pack_content_size() if self.char_pack is not None else self.current_pixmap.size())

        # Position window - defaults to bottom-right
        self.load_position()

        # Setup context menu
        self.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_context_menu)

        # Schedule first animation pass (GIF chars only)
        if self.char_pack is None:
            self.schedule_next_animation()

        # Save current image to INI on startup
        save_image_to_ini(self.file_name)

        # Reminder scheduler (avatar-on-a-plane flyby). Loads any saved reminder
        # and re-arms it; the flyby UI is imported lazily on first use.
        self.reminder_controller = reminder.ReminderController(self)

        # Shared announcement queue: every companion feature (focus sessions,
        # GitHub, calendar, digest) flies its banners through this one object
        # so flybys never overlap and focus time stays quiet.
        self.announcer = announcer.Announcer(self)

        # Pomodoro-style focus sessions: Brok settles down while you work,
        # a thin bar under it shows the remaining time, banners mark breaks.
        self.focus_controller = focus.FocusController(self, announcer=self.announcer)

        # GitHub notifications (opt-in, BYO token): silent — zero network
        # requests — until enabled in its settings dialog.
        self.github_notifier = github_notify.GitHubNotifier(self, announcer=self.announcer)

        # Calendar reminders (opt-in, secret ICS URL): banners shortly before
        # each event, shown like every other announcement.
        self.calendar_controller = calendar_ics.CalendarController(self, announcer=self.announcer)

        # Activity diary (on by default, local-only): counters, never content;
        # the collector shares activity.db with the focus session log above.
        self.activity_collector = activity.ActivityCollector(store=self.focus_controller.store)
        # Auto-pomodoro: coming back to the keyboard after an idle stretch
        # quietly starts the focus countdown ([focus] auto_start to disable).
        self.focus_controller.attach_collector(self.activity_collector)

        # The morning newspaper: yesterday's stats once per day, first thing
        # after 05:00 — another small reason the avatar is running at dawn.
        self.morning_digest = digest.MorningDigest(self.focus_controller.store, announcer=self.announcer)

    def setup_gif_content(self, png_pixmap, gif_movie, gif_data) -> None:
        """Legacy single-GIF char: static first frame + play-once animation."""
        self.png_pixmap = png_pixmap
        self.gif_movie = gif_movie
        self.gif_data = gif_data
        self.current_pixmap = self.png_pixmap
        self.gif_movie.jumpToFrame(0)
        original_size = self.gif_movie.currentPixmap().size()
        self.original_size = original_size
        self.gif_duration, self.frame_delays = get_gif_duration(self.gif_movie, self.gif_data)
        if not self.frame_delays:
            frame_count = self.gif_movie.frameCount()
            if frame_count > 0 and self.gif_duration > 0:
                self.frame_delays = [int((self.gif_duration / frame_count) * 1000)] * frame_count
            else:
                self.frame_delays = [100]
        self.first_frame_pixmap = self.png_pixmap.copy()
        self.state = 'png'
        self.gif_movie.setCacheMode(QtGui.QMovie.CacheMode.CacheAll)
        self.gif_movie.setSpeed(100)
        self.animation_timer = QtCore.QTimer(self)
        self.animation_timer.timeout.connect(self.on_animation_frame)
        self.current_frame = 0
        gif_size = self.gif_movie.scaledSize()
        logger.info(
            f"Playing {self.file_name}.zip {original_size.width()}x{original_size.height()} > "
            f"{gif_size.width()}x{gif_size.height()} (first_frame, {self.wait_time:.1f}s static)"
        )

    def all_pack_clips(self):
        """Every Anim in the pack (for hardening / preprocessing)."""
        pack = self.char_pack
        clips = list(pack.anims) + list(pack.idle_anims) + list(pack.click_anims) + list(pack.hungry_anims)
        clips += [a for a in (pack.sleep_in, pack.sleep_out, pack.yawn) if a is not None]
        return clips

    def pack_content_size(self) -> QtCore.QSize:
        """Bounding box over the static and every frame, so the window fits the
        largest pose. Frames are box-fit independently and a body GIF may be taller
        than the still; the window must hold it or it would be clipped. Each frame
        is centred within this box at paint time."""
        pack = self.char_pack
        width, height = pack.static.width(), pack.static.height()
        for still in (pack.blink, pack.sleep):
            if still is not None:
                width, height = max(width, still.width()), max(height, still.height())
        for anim in self.all_pack_clips():
            for frame in anim.frames:
                width, height = max(width, frame.width()), max(height, frame.height())
        return QtCore.QSize(width, height)

    def setup_pack_content(self) -> None:
        """Interactive char pack: drives the state machine (awake/blink/click/idle/yawn/sleep/hungry)."""
        pack = self.char_pack
        # No compositor → snap body-frame edges to binary alpha (crisp, no fringe).
        # Pupil sprites stay smooth (drawn over the opaque face, never fringe).
        if self.shape_mask_enabled:
            pack.static = harden_pixmap(pack.static)
            for still in ("blink", "sleep"):
                if getattr(pack, still) is not None:
                    setattr(pack, still, harden_pixmap(getattr(pack, still)))
            for anim in self.all_pack_clips():
                anim.frames = [harden_pixmap(frame) for frame in anim.frames]
        self.png_pixmap = pack.static
        self.gif_movie = None
        self.gif_data = b""
        self.current_pixmap = pack.static
        self.first_frame_pixmap = pack.static.copy()
        self.original_size = pack.static.size()
        self.state = 'png'
        self.gif_duration, self.frame_delays = 0.0, []
        self.eye_clock = QtCore.QElapsedTimer()
        self.eye_clock.start()
        self.test_now = None                 # tests inject time here
        now = self.pack_now()

        # --- state-machine state ---
        self.base_state = "awake"             # "awake" | "sleeping"
        self.active_clip = None               # (anim, start_t, next_state) one-shot
        self.squint_until = -10.0
        self.yawned = False
        self.last_interaction = now           # mouse over the avatar / click / drag
        self.last_cursor_move = now           # global cursor movement
        self.next_blink = now + random.uniform(*pack.blink_every) if pack.blink_enabled else float("inf")
        self.next_idle = now + random.uniform(*pack.idle_random_every)
        self.next_hungry = now + random.uniform(*pack.hungry_every)
        self.anim_next = [now + random.uniform(*anim.every) for anim in pack.anims]
        self.battery_pct = None
        self.battery_checked = -1e9
        self.pack_mode = "open"
        self.last_cursor = QtGui.QCursor.pos()
        self.mask_cache: dict = {}

        self.pack_timer = QtCore.QTimer(self)
        self.pack_timer.timeout.connect(self.pack_tick)
        from . import profile as _profile

        self.pack_timer.start(_profile.active().tick_ms)  # ~30 fps by default; only repaints when something changed
        logger.info(
            f"Loaded interactive char '{pack.name}' ({pack.static.width()}x{pack.static.height()}; "
            f"eyes={pack.eyes is not None} blink={pack.blink_enabled} "
            f"sleep={pack.sleep is not None} yawn={pack.yawn is not None} "
            f"idle={len(pack.idle_anims)} click={len(pack.click_anims)} "
            f"hungry={len(pack.hungry_anims)} anims={len(pack.anims)})"
        )

    def pack_now(self) -> float:
        if getattr(self, "test_now", None) is not None:
            return self.test_now
        return self.eye_clock.elapsed() / 1000.0

    def pack_tick(self) -> None:
        """Advance the state machine; repaint only when the frame or gaze changes."""
        now = self.pack_now()
        cursor = QtGui.QCursor.pos()
        moved = cursor != self.last_cursor
        if moved:
            self.last_cursor = cursor
            self.last_cursor_move = now
            self.yawned = False
        previous = self.current_pixmap
        self.pack_mode = self.update_pack_frame()
        changed = self.current_pixmap is not previous
        if moved and self.pack_mode == "open" and self.char_pack.eyes is not None:
            changed = True
        if changed:
            self.update()

    def clip_frame(self, anim, age_ms: float):
        accumulated = 0
        for frame, delay in zip(anim.frames, anim.delays):
            accumulated += delay
            if age_ms < accumulated:
                return frame
        return anim.frames[-1]

    def start_clip(self, anim, next_state: str, now: float) -> None:
        self.active_clip = (anim, now, next_state)
        if anim.frames:
            self.current_pixmap = anim.frames[0]

    def wake(self, now: float) -> bool:
        """If asleep (or falling asleep), wake via sleep_out (or instantly). True if woke."""
        going_to_sleep = self.active_clip is not None and self.active_clip[2] == "sleeping"
        if self.base_state != "sleeping" and not going_to_sleep:
            return False
        self.last_interaction = now      # waking is an interaction; don't re-sleep/yawn instantly
        self.last_cursor_move = now
        self.yawned = False
        if self.char_pack.sleep_out is not None:
            self.start_clip(self.char_pack.sleep_out, "awake", now)
        else:
            self.active_clip = None
            self.base_state = "awake"
        return True

    def battery_low(self) -> bool:
        now = self.pack_now()
        if now - self.battery_checked > 10.0:
            self.battery_checked = now
            self.battery_pct = read_battery_percent()
        return self.battery_pct is not None and self.battery_pct <= self.char_pack.hungry_below

    def on_pack_click(self) -> None:
        """Click reaction: wake if asleep, else play a clickN anim or squint."""
        if self.char_pack is None:
            return
        now = self.pack_now()
        self.last_interaction = now
        self.yawned = False
        if self.wake(now):
            self.update()
            return
        pack = self.char_pack
        if pack.click_anims:
            self.start_clip(random.choice(pack.click_anims), "awake", now)
        elif pack.blink is not None:
            self.squint_until = now + pack.click_squint
        self.update()

    def update_pack_frame(self) -> str:
        """State machine: hungry > sleep > yawn > reaction > blink > awake. Sets current_pixmap."""
        pack = self.char_pack
        now = self.pack_now()

        # An active one-shot clip (transition or reaction) plays to completion.
        if self.active_clip is not None:
            anim, start, next_state = self.active_clip
            age_ms = (now - start) * 1000.0
            if not anim.frames or age_ms >= sum(anim.delays):
                self.active_clip = None
                if next_state:
                    self.base_state = next_state
            else:
                self.current_pixmap = self.clip_frame(anim, age_ms)
                return "anim"

        # Held sleeping pose (wake is driven by interaction, not here).
        if self.base_state == "sleeping":
            self.current_pixmap = pack.sleep or pack.static
            return "sleep"

        idle_for = now - self.last_interaction
        cursor_still = now - self.last_cursor_move

        # hungry (low battery)
        if pack.hungry_anims and now >= self.next_hungry and self.battery_low():
            self.start_clip(random.choice(pack.hungry_anims), "awake", now)
            self.next_hungry = now + random.uniform(*pack.hungry_every)
            return "anim"
        # sleep
        if (pack.sleep is not None or pack.sleep_in is not None) and idle_for > pack.sleep_after:
            if pack.sleep_in is not None:
                self.start_clip(pack.sleep_in, "sleeping", now)
                return "anim"
            self.base_state = "sleeping"
            self.current_pixmap = pack.sleep or pack.static
            return "sleep"
        # yawn (precursor to sleep)
        if pack.yawn is not None and not self.yawned and cursor_still > pack.yawn_after:
            self.yawned = True
            self.start_clip(pack.yawn, "awake", now)
            return "anim"
        # idle-random pool
        if pack.idle_anims and now >= self.next_idle:
            self.start_clip(random.choice(pack.idle_anims), "awake", now)
            self.next_idle = now + random.uniform(*pack.idle_random_every)
            return "anim"
        # periodic config animations
        for index, anim in enumerate(pack.anims):
            if now >= self.anim_next[index]:
                self.start_clip(anim, "awake", now)
                self.anim_next[index] = now + sum(anim.delays) / 1000.0 + random.uniform(*anim.every)
                return "anim"
        # blink
        if pack.blink_enabled and now >= self.next_blink:
            self.squint_until = now + pack.blink_duration
            self.next_blink = now + random.uniform(*pack.blink_every)
        squinting = now < self.squint_until
        self.current_pixmap = pack.blink if (squinting and pack.blink is not None) else pack.static
        return "blink" if squinting else "open"

    def pupil_offsets(self, x: int, y: int, cursor: QtCore.QPoint):
        """Gaze offsets (scaled px) for the (left, right) pupils.

        Both pupils share one angle — that of whichever eye is nearer the cursor.
        When the cursor is outside the eye pair they move in parallel (the same
        offset); when it is horizontally between the eyes they mirror each other
        (the nearer eye aims at the cursor, the other takes the horizontal
        mirror), so the gaze converges. Sockets sit at equal height, so the two
        cases meet continuously at the boundaries. Returns ((lox, loy), (rox, roy))."""
        pack = self.char_pack
        travel = pack.eyes.travel_radius
        left_socket = self.mapToGlobal(QtCore.QPoint(round(x + pack.eyes.left.x()), round(y + pack.eyes.left.y())))
        right_socket = self.mapToGlobal(QtCore.QPoint(round(x + pack.eyes.right.x()), round(y + pack.eyes.right.y())))

        def aim(socket):
            dx, dy = cursor.x() - socket.x(), cursor.y() - socket.y()
            dist = math.hypot(dx, dy)
            return (dx / dist * travel, dy / dist * travel) if dist > 1 else (0.0, 0.0)

        left_dist = math.hypot(cursor.x() - left_socket.x(), cursor.y() - left_socket.y())
        right_dist = math.hypot(cursor.x() - right_socket.x(), cursor.y() - right_socket.y())
        left_nearer = left_dist <= right_dist
        base = aim(left_socket if left_nearer else right_socket)

        if left_socket.x() < cursor.x() < right_socket.x():     # between the eyes -> converge (mirror)
            mirrored = (-base[0], base[1])
            return (base, mirrored) if left_nearer else (mirrored, base)
        return base, base                                       # outside the pair -> parallel

    def gaze_target(self, x: int, y: int) -> QtCore.QPoint:
        """Where the pupils look: the cursor while "Enable Tracking" is on AND the
        cursor is on the avatar's screen; otherwise the avatar's own nose — a point
        between and just below the eyes so the pupils converge downward. So the avatar
        looks at its nose when Tracking is off, or when the cursor has left for
        another monitor. (Independent of the Mouse/Keyboard diary toggles.)"""
        collector = getattr(self, "activity_collector", None)
        tracking = collector is None or collector.settings.enabled
        if tracking:
            cursor = QtGui.QCursor.pos()
            app = QtWidgets.QApplication.instance()
            cat_screen = self.screen()
            if app is not None and cat_screen is not None and app.screenAt(cursor) is cat_screen:
                return cursor
        eyes = self.char_pack.eyes
        nose_x = (eyes.left.x() + eyes.right.x()) / 2.0
        nose_y = max(eyes.left.y(), eyes.right.y()) + eyes.travel_radius * 2
        return self.mapToGlobal(QtCore.QPoint(round(x + nose_x), round(y + nose_y)))

    def draw_pupils(self, painter, x: int, y: int) -> None:
        """Draw the L/R pupil sprites at the computed gaze offsets."""
        pack = self.char_pack
        if not pack.eyes or pack.eye_left is None or pack.eye_right is None:
            return
        left_off, right_off = self.pupil_offsets(x, y, self.gaze_target(x, y))
        for center, sprite, (ox, oy) in (
            (pack.eyes.left, pack.eye_left, left_off),
            (pack.eyes.right, pack.eye_right, right_off),
        ):
            px = x + center.x() + ox - sprite.width() / 2.0
            py = y + center.y() + oy - sprite.height() / 2.0
            painter.drawPixmap(QtCore.QPointF(px, py), sprite)


    def load_image(self, image_name: str) -> None:
        """Switch chars — a new interactive pack or a legacy single-GIF."""
        zip_path = char_catalog.find_char(image_name)
        if zip_path is None:
            logger.error(f"ZIP file not found for char: {image_name}")
            return
        if char_pack.is_new_pack(zip_path):
            self.switch_to_pack(image_name, zip_path)
            return
        # Decode the new char into locals first — a failure here must not leave
        # the window half-switched. Only once everything is built do we commit
        # to self.* and resize the window (mirrors switch_to_pack).
        try:
            with char_pack.CharSource(zip_path) as source:
                gif_files = sorted(n for n in source.names() if n.lower().endswith(".gif"))
                if not gif_files:
                    logger.error("No GIF found in char: %s", image_name)
                    return
                gif_data = source.read(gif_files[0])
                logger.info("Extracted %s from %s", gif_files[0], Path(zip_path).name)

            new_movie = movie_from_gif_bytes(gif_data)
            new_movie.jumpToFrame(0)
            first_frame = new_movie.currentPixmap()
            if first_frame.isNull():
                logger.error("Failed to extract first frame from %s.zip", image_name)
                return

            source_size = first_frame.size()
            new_pixmap = scale_pixmap_if_needed(first_frame, IMAGE_WIDTH_MAX, IMAGE_HEIGHT_MAX)
            if new_pixmap.isNull():
                logger.error("Failed to render first frame from %s.zip", image_name)
                return
            if source_size != new_pixmap.size():
                logger.info(
                    "Resized %s.zip: %dx%d -> %dx%d",
                    image_name,
                    source_size.width(), source_size.height(),
                    new_pixmap.width(), new_pixmap.height(),
                )

            new_movie.setScaledSize(new_pixmap.size())
            new_movie.setSpeed(100)
            new_movie.jumpToFrame(0)
            movie_frame_size = new_movie.currentPixmap().size()
            gif_duration, frame_delays = get_gif_duration(new_movie, gif_data)
        except Exception:  # noqa: BLE001 -- a bad char must never corrupt the current one
            logger.exception("Error loading %s", image_name)
            return

        if not frame_delays:
            frame_count = new_movie.frameCount()
            if frame_count > 0 and gif_duration > 0:
                frame_delays = [int((gif_duration / frame_count) * 1000)] * frame_count
            else:
                frame_delays = [100]  # default 100ms per frame

        # Decoded cleanly — commit the switch. The Qt calls below don't raise, so
        # the old char stays fully intact if anything above failed.
        if self.char_pack is not None:
            self.teardown_pack_mode()
        self.png_pixmap = new_pixmap
        self.gif_movie = new_movie
        self.gif_data = gif_data
        self.file_name = image_name
        self.original_size = movie_frame_size
        self.gif_duration = gif_duration
        self.frame_delays = frame_delays
        self.first_frame_pixmap = new_pixmap.copy()

        self.current_pixmap = self.png_pixmap
        self.state = 'png'
        self.animation_timer.stop()
        self.schedule_next_animation()

        # Keep the bottom-right corner fixed across the resize.
        old_size = self.size()
        top_left = self.pos()
        bottom_right_x = top_left.x() + old_size.width()
        bottom_right_y = top_left.y() + old_size.height()
        self.resize(self.png_pixmap.size())
        new_size = self.png_pixmap.size()
        self.move(bottom_right_x - new_size.width(), bottom_right_y - new_size.height())

        save_image_to_ini(image_name)
        self.save_position()
        logger.info("Switched to %s.zip %dx%d", image_name, self.png_pixmap.width(), self.png_pixmap.height())
        self.update()

    def teardown_pack_mode(self) -> None:
        """Leave interactive-pack mode so the legacy GIF path can take over."""
        if getattr(self, "pack_timer", None) is not None:
            self.pack_timer.stop()
            self.pack_timer = None
        self.char_pack = None
        if getattr(self, "animation_timer", None) is None:
            self.animation_timer = QtCore.QTimer(self)
            self.animation_timer.timeout.connect(self.on_animation_frame)
        self.current_frame = 0

    def switch_to_pack(self, image_name: str, zip_path) -> None:
        """Switch to a new interactive char pack, preserving the bottom-right corner."""
        try:
            pack = char_pack.load_pack(zip_path)
        except Exception as exc:
            logger.error(f"Error loading pack {image_name}: {exc}")
            return
        if getattr(self, "animation_timer", None) is not None:
            self.animation_timer.stop()
        if getattr(self, "pack_timer", None) is not None:
            self.pack_timer.stop()
        old_size = self.size()
        top_left = self.pos()
        bottom_right_x = top_left.x() + old_size.width()
        bottom_right_y = top_left.y() + old_size.height()

        self.char_pack = pack
        self.file_name = image_name
        self.setup_pack_content()

        new_size = self.pack_content_size()
        self.resize(new_size)
        self.move(bottom_right_x - new_size.width(), bottom_right_y - new_size.height())
        save_image_to_ini(image_name)
        self.save_position()
        self.update()
        logger.info(f"Switched to interactive char {image_name}")

    def show_context_menu(self, pos: QtCore.QPoint) -> None:
        """Show context menu at the given position."""
        menu = QtWidgets.QMenu(self)
        visible = menu_config.load_menu_visibility()

        # "Chat" appears only once Ollama is configured (a controller exists),
        # and is greyed out while the LLM is disabled.
        toggle_chat = getattr(self, "toggle_llm_chat", None)
        if callable(toggle_chat) and visible["chat"]:
            chat_action = menu.addAction(i18n.tr("Chat"))
            chat_action.triggered.connect(toggle_chat)
            llm_is_enabled = getattr(self, "is_llm_enabled", None)
            if callable(llm_is_enabled):
                chat_action.setEnabled(bool(llm_is_enabled()))
            menu.addSeparator()

        # Feature entries, in the agreed order: LLM, Calendar, Reminder,
        # GitHub, Activity. Each can be hidden from the Settings dialog.
        if visible["llm"]:
            menu.addAction(i18n.tr("LLM…")).triggered.connect(self.open_llm_settings)
        menu.addAction(i18n.tr("Coding Workspace…")).triggered.connect(self.open_workspace)
        menu.addAction(i18n.tr("Privacy…")).triggered.connect(self.open_privacy)
        if visible["calendar"]:
            menu.addAction(i18n.tr("Calendar…")).triggered.connect(self.open_calendar_settings)
        if visible["reminder"]:
            menu.addAction(i18n.tr("Reminder…")).triggered.connect(self.open_reminder)
        if visible["github"]:
            menu.addAction(i18n.tr("GitHub…")).triggered.connect(self.open_github_settings)
        if visible["activity"]:
            menu.addAction(i18n.tr("Activity…")).triggered.connect(self.open_activity_dialog)

        # Shop temporarily hidden from the menu (work in progress). The dialog
        # and its handler stay in the codebase; re-enable by uncommenting:
        # shop_action = menu.addAction("Open Shop…")
        # shop_action.triggered.connect(self.open_shop)

        # Focus is fully automatic now (earned from activity) — no menu action.
        menu.addSeparator()

        # Settings, Chars and Language share one block (no separators between
        # them). Settings is always shown — it's how hidden entries are brought
        # back.
        settings_action = menu.addAction(i18n.tr("Settings…"))
        settings_action.triggered.connect(self.open_settings)

        # Chars sits under Settings. Rebuild the list every time so freshly
        # installed chars appear without a restart.
        self.available_images = char_catalog.scan_all()
        if len(self.available_images) > 0 and visible["chars"]:
            images_menu = menu.addMenu(i18n.tr("Chars"))
            create_action = images_menu.addAction(i18n.tr("Generate…"))
            create_action.triggered.connect(self.open_ai_char)
            generated_chars = char_catalog.ai_generated_chars()
            if generated_chars:
                delete_menu = images_menu.addMenu(i18n.tr("Delete…"))
                for custom_id in generated_chars:
                    delete_action = delete_menu.addAction(custom_id)
                    delete_action.triggered.connect(
                        lambda checked=False, name=custom_id: self.delete_ai_char(name)
                    )
            images_menu.addSeparator()
            for img_name in self.available_images:
                action = images_menu.addAction(img_name)
                if img_name == self.file_name:
                    action.setCheckable(True)
                    action.setChecked(True)
                action.triggered.connect(lambda checked, name=img_name: self.load_image(name))

        # Language picker.
        menu.addMenu(i18n.build_language_menu(CFG_FILE))

        # Close the Settings / Chars / Language block before the utilities.
        menu.addSeparator()

        reset_action = menu.addAction(i18n.tr("Reset"))
        reset_action.triggered.connect(self.reset_position)

        update_action = menu.addAction(i18n.tr("Update…"))
        update_action.triggered.connect(self.open_update)

        if autostart.is_supported():
            login_action = menu.addAction(i18n.tr("Autostart"))
            login_action.setCheckable(True)
            login_action.setChecked(autostart.is_enabled())
            login_action.toggled.connect(autostart.set_enabled)

        # With a system tray, "Close" from the avatar menu only hides it to the tray
        # (reopen from the tray's Open, or a tray double-click); the real Quit
        # lives only in the tray menu. Without a tray there's nowhere to hide, so
        # keep a real Quit here.
        if getattr(self, "tray_icon", None) is not None:
            close_action = menu.addAction(i18n.tr("Close"))
            close_action.triggered.connect(self.hide)
        else:
            quit_action = menu.addAction(i18n.tr("Quit"))
            quit_action.triggered.connect(QtWidgets.QApplication.quit)
        tidy_separators(menu)
        menu.exec(self.mapToGlobal(pos))



    
    def schedule_next_animation(self) -> None:
        """Schedule the next PNG -> GIF transition with a single-shot timer."""
        delay_ms = max(0, int(self.wait_time * 1000))
        QtCore.QTimer.singleShot(delay_ms, self.start_animation)

    def start_animation(self) -> None:
        """Switch from static PNG to one-shot GIF playback."""
        if self.state != 'png':
            return

        gif_size = self.gif_movie.scaledSize()
        logger.debug(
            f"Playing {self.file_name}.zip {self.original_size.width()}x{self.original_size.height()} > "
            f"{gif_size.width()}x{gif_size.height()} (animation, {self.gif_duration:.2f}s)"
        )
        self.state = 'gif'

        # Reset to the in-memory first frame for a fresh start
        if not self.png_pixmap.isNull():
            self.current_pixmap = self.png_pixmap
            self.update()

        # Recreate the movie from the in-memory GIF bytes for a fresh start
        self.gif_movie = movie_from_gif_bytes(self.gif_data)
        self.gif_movie.setScaledSize(self.current_pixmap.size())
        self.gif_movie.setCacheMode(QtGui.QMovie.CacheMode.CacheAll)
        self.gif_movie.setSpeed(100)
        self.gif_movie.jumpToFrame(0)

        # Start manual frame-by-frame animation with per-frame delays
        self.current_frame = 0
        self.animation_timer.stop()
        if self.frame_delays:
            self.animation_timer.start(self.frame_delays[0])
        else:
            self.animation_timer.start(100)

    def on_animation_frame(self) -> None:
        """Manually advance to next frame at controlled speed."""
        frame_count = self.gif_movie.frameCount()

        # Check if we've completed the animation
        if self.current_frame >= frame_count:
            self.animation_timer.stop()
            logger.debug(f"Animation complete for {self.file_name} ({frame_count} frames)")
            QtCore.QTimer.singleShot(50, self.complete_switch_to_png)
            return

        # Jump to current frame and display it
        self.gif_movie.jumpToFrame(self.current_frame)
        pixmap = self.gif_movie.currentPixmap()
        if not pixmap.isNull():
            self.current_pixmap = pixmap
            self.update()

        # Move to next frame
        self.current_frame += 1

        # If not done, stop current timer and restart with next frame's delay
        if self.current_frame < frame_count and self.frame_delays and self.current_frame < len(self.frame_delays):
            delay = self.frame_delays[self.current_frame]
            self.animation_timer.stop()
            self.animation_timer.start(delay)

    def complete_switch_to_png(self) -> None:
        """Complete the switch from GIF to PNG state."""
        if self.state == 'gif':
            # Switch to PNG state
            self.state = 'png'

            # Reuse the in-memory first frame
            static_pixmap = self.png_pixmap
            if not static_pixmap.isNull():
                self.current_pixmap = static_pixmap
                self.first_frame_pixmap = static_pixmap

            logger.debug(
                f"Playing {self.file_name}.zip {self.original_size.width()}x{self.original_size.height()} > "
                f"{self.png_pixmap.width()}x{self.png_pixmap.height()} (first_frame, {self.wait_time:.1f}s static)"
            )
            self.update()
            self.schedule_next_animation()

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        """Paint the current pixmap (+ tracking pupils for interactive chars)."""
        mode = getattr(self, "pack_mode", None) if self.char_pack is not None else None

        # Centre the pixmap in the widget.
        widget_rect = self.rect()
        pixmap_rect = self.current_pixmap.rect()
        x = (widget_rect.width() - pixmap_rect.width()) // 2
        y = (widget_rect.height() - pixmap_rect.height()) // 2

        # Update the silhouette mask BEFORE painting: the backing-store -> screen
        # blit at the end of this paint is clipped to the *current* mask, so any
        # pixels newly revealed by a shape change (e.g. switching to a char
        # with a larger silhouette) must be inside the mask now, or they never
        # get blitted and stay as stale/black framebuffer until the next repaint.
        if self.shape_mask_enabled:
            self.refresh_shape_mask(x, y)

        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        painter.drawPixmap(x, y, self.current_pixmap)
        if mode == "open":
            self.draw_pupils(painter, x, y)
        painter.end()

    def refresh_shape_mask(self, x: int, y: int) -> None:
        """Clip the window to the current pixmap's alpha silhouette (no-compositor path).

        Recomputed only when the frame/position actually changes (cache key guard),
        so the setMask never triggers a repaint loop.
        """
        pixmap = self.current_pixmap
        key = (pixmap.cacheKey(), x, y, self.width(), self.height())
        if key == self.shape_mask_key:
            return
        self.shape_mask_key = key

        # Reuse the silhouette region per frame — building QRegion from a big
        # bitmap each paint is what made multi-frame chars lag.
        cache = getattr(self, "mask_cache", None)
        region = cache.get(pixmap.cacheKey()) if cache is not None else None
        if region is None:
            bitmap = pixmap.mask()
            if bitmap.isNull():
                self.clearMask()
                return
            region = QtGui.QRegion(bitmap)
            if cache is not None:
                cache[pixmap.cacheKey()] = region
        self.setMask(region.translated(x, y) if (x or y) else region)

        # Growing the shape reveals window area the X server does not auto-expose
        # (no compositor), so the just-painted backing store never reaches those
        # newly-unmasked pixels — they linger as stale/black framebuffer. Schedule
        # one more paint now that the new mask is in effect to fill them. The
        # cache-key guard above makes that follow-up paint a no-op for the mask,
        # so this settles in a single extra frame (no repaint loop). Without it a
        # char switch onto a static frame freezes the gap as black until the
        # next animation happens to repaint everything.
        self.update()

    def enterEvent(self, event: QtCore.QEvent) -> None:
        """Show the current-period tooltip immediately — no hover delay."""
        tip = self.toolTip()
        if tip:
            QtWidgets.QToolTip.showText(QtGui.QCursor.pos(), tip, self)
        super().enterEvent(event)

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        """Handle mouse press for dragging (+ click reaction / wake on interactive chars)."""
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self.on_pack_click()
            self.dragging = True
            self.drag_start_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:
        """Handle mouse move for dragging (+ counts as interaction: resets idle, wakes)."""
        if self.char_pack is not None:
            now = self.pack_now()
            self.last_interaction = now
            self.wake(now)
        if self.dragging and event.buttons() == QtCore.Qt.MouseButton.LeftButton:
            new_pos = event.globalPosition().toPoint() - self.drag_start_pos
            self.move(new_pos)

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
        """Handle mouse release to stop dragging and save position."""
        if event.button() == QtCore.Qt.MouseButton.LeftButton and self.dragging:
            self.dragging = False
            self.save_position()

def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Brok desktop robot overlay with GIF animation (first frame used as static image)."
    )
    parser.add_argument(
        "-i", "--image",
        type=str,
        default=None,
        help="Path to ZIP file containing GIF (default: the bundled Brok robot). First frame used as static image.",
    )
    parser.add_argument(
        "--wait",
        type=float,
        default=STATIC_TIME,
        help="Seconds to show first frame before playing GIF (default: 5.0)",
    )

    parser.add_argument(
        "--pos",
        nargs=2,
        type=int,
        metavar=("X", "Y"),
        help="Start position (overrides remembered position)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable verbose DEBUG logging (per-frame animation cycle, GIF timing, etc.)",
    )
    llm.add_arguments(parser)
    return parser.parse_args()

































def main() -> None:
    paths.migrate_legacy_config()
    """Main entry point."""
    args = parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    from . import profile as _profile

    prof = _profile.active()
    _profile.apply_environment(prof)
    if prof.debug_logging:
        logging.getLogger().setLevel(logging.DEBUG)

    app_version = update_check.current_version()
    logger.info("brok %s (profile: %s)", app_version, prof.name)
    if prof.check_updates:
        update_check.check_in_background(app_version)

    # Apply the saved UI language before any window or menu is built.
    i18n.load_language(CFG_FILE)

    llm_context = llm.initialize(args)
    
    # Suppress Qt D-Bus warnings on Linux
    os.environ.setdefault("QT_LOGGING_RULES", "qt.qpa.theme.gnome=false")
    os.environ.setdefault("QT_QPA_PLATFORM_PLUGIN_PATH", "")
    os.environ.setdefault("QT_QPA_NO_NATIVE_MENUBAR", "1")

    # Suppress additional Qt warnings
    warnings.filterwarnings("ignore", category=DeprecationWarning)

    # Headless/VNC X servers may expose a framebuffer with no RANDR monitor,
    # which makes Qt see a 0x0 screen (breaks positioning and menu popups).
    # Register a virtual monitor before the QApplication reads screen geometry.
    ensure_virtual_monitor()

    # WM_CLASS instance name (read by Qt at QApplication construction). Without
    # this the taskbar uses the script name ("main.py") and groups brok with
    # other python apps launched the same way.
    os.environ.setdefault("RESOURCE_NAME", "brok")

    # Windows taskbar identity. Without an explicit AppUserModelID a frozen
    # PySide6 app is treated as its host process, so the taskbar shows a generic
    # icon instead of ours — setWindowIcon() alone does not fix this. Set it
    # before the QApplication builds any window; mirrors the macOS bundle id.
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("app.brok")
        except Exception as app_id_error:
            logger.debug("Could not set the Windows AppUserModelID: %s", app_id_error)

    # Initialize Qt application with error handling
    try:
        app = QtWidgets.QApplication(sys.argv)
        app.setQuitOnLastWindowClosed(True)
        ensure_emoji_font(app)
        app.setWindowIcon(make_app_icon())  # 😽 — used for the taskbar entry and dialogs
        # Give the window a distinct WM_CLASS so the taskbar doesn't group it with
        # other python "main.py" apps. setDesktopFileName drives the X11 class.
        i18n.apply_layout_direction(app)  # RTL for Persian/Arabic/Hebrew
        app.setApplicationName("brok")
        app.setDesktopFileName("brok")
        install_desktop_entry()  # so brok shows in the Linux applications menu
        platform_name = (app.platformName() or "").lower()
    except Exception as e:
        logger.error(f"Failed to initialize Qt application: {e}")
        sys.exit(1)
    
    # Single instance: a second launch must not spawn a second cat. Hold the
    # lock for the whole process lifetime (it is released when the process
    # exits). A lock left by a crashed instance is reclaimed automatically
    # because QLockFile records the owner PID and detects a dead owner.
    if platform_name != "offscreen":
        CFG_DIR.mkdir(parents=True, exist_ok=True)
        instance_lock = QtCore.QLockFile(str(CFG_DIR / "brok.lock"))
        instance_lock.setStaleLockTime(0)
        if not instance_lock.tryLock(100):
            logger.info("Another brok instance is already running — raising it and exiting.")
            activate_running_instance(SINGLE_INSTANCE_NAME)
            sys.exit(0)

    # Setup signal handlers for graceful shutdown
    def signal_handler(signum, frame):
        """Handle Ctrl+C gracefully."""
        logger.info("\nReceived interrupt signal, shutting down...")
        app.quit()
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Allow signal handling during Qt event loop
    timer = QtCore.QTimer()
    timer.timeout.connect(lambda: None)  # Allow Python signal handlers to run
    timer.start(100)  # Check every 100ms
    
    # Scan for available ZIP files
    available_images = scan_chars()
    logger.info(f"Found {len(available_images)} ZIP archive(s): {', '.join(available_images)}")
    
    # Load default image from INI if no image path provided
    default_image = None
    if not args.image:
        default_image = load_image_from_ini()
        if default_image and default_image not in available_images:
            logger.warning(f"Image '{default_image}' from INI not found in available images, using default image")
            default_image = None
    
    # Resolve the chosen char's ZIP, then branch on format: a new interactive
    # pack (static/blink/eyes/config) or a legacy single-GIF char.
    try:
        if args.image:
            zip_path = Path(args.image)
        else:
            zip_path = (char_catalog.find_char(default_image or DEFAULT_CHAR)
                        or char_catalog.find_char(DEFAULT_CHAR) or char_catalog.find_char("cat"))
        if zip_path and char_pack.is_new_pack(zip_path):
            pack = char_pack.load_pack(zip_path)
            window = BrokWindow(pack.static, None, args.wait, Path(zip_path).stem,
                                    available_images, b"", pack=pack)
        else:
            png_pixmap, gif_movie, file_name, gif_data = load_packaged_images(args.image, default_image)
            logger.info(
                f"Playing {file_name}.zip (first frame) "
                f"{png_pixmap.width()}x{png_pixmap.height()} for {args.wait:.1f}s"
            )
            window = BrokWindow(png_pixmap, gif_movie, args.wait, file_name, available_images, gif_data)
    except Exception as e:
        logger.error(f"Error loading char: {e}")
        sys.exit(2)
    if llm_context:
        llm.attach(window, llm_context)
    
    if args.pos:
        window.move(args.pos[0], args.pos[1])

    if platform_name == "offscreen":
        logger.info("Offscreen platform detected: skipping window display.")
        QtCore.QTimer.singleShot(0, app.quit)
    else:
        window.show()
        # Persistent cat tray icon (kept on the window so it isn't GC'd).
        window.tray_icon = setup_tray(app, window)
        # Safety net: let a second launch raise this window, so a cat hidden to a
        # tray the panel doesn't render can always be brought back with `brok`.
        window.activation_server = start_activation_server(SINGLE_INSTANCE_NAME, window)
        try:  # configurable global hotkey (default Ctrl+Space); degrades gracefully, never blocks startup
            from .hotkey_qt import start_hotkey

            window.hotkey_bridge = start_hotkey(window)
        except Exception:
            logger.exception("Global hotkey setup failed")
        if sys.platform == "darwin" and window.tray_icon is not None:
            install_macos_reopen(app, window)
        # Live in the tray: hiding/closing windows no longer quits the app —
        # only the explicit Quit action does. With no tray to quit from, keep
        # the old behaviour so the user is never stuck with an invisible process.
        app.setQuitOnLastWindowClosed(window.tray_icon is None)
        # Flush the in-progress activity minute on a clean Quit.
        app.aboutToQuit.connect(lambda: flush_activity_on_quit(window))
        # First-run nudge to start on login, 15 s after the avatar is up: the avatar
        # is the first thing a new user sees, not a dialog in front of it.
        QtCore.QTimer.singleShot(15000, lambda: offer_autostart_on_first_run(window))

    try:
        sys.exit(app.exec())
    except KeyboardInterrupt:
        logger.info("\nShutdown requested by user")
        sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("\nShutdown requested by user")
        sys.exit(0)


# Backwards-compatible alias (old tests/plugins imported the upstream class name).
PixelCatWindow = BrokWindow
