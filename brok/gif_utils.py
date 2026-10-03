"""GIF/pixmap helpers for the Brok overlay (frame delays, scaling, 1-bit mask hardening)."""

from __future__ import annotations

import io
import logging

from PySide6 import QtCore, QtGui

logger = logging.getLogger(__name__)


def movie_from_gif_bytes(gif_data: bytes) -> QtGui.QMovie:
    """A QMovie that reads the GIF from memory (a QBuffer), not a temp file.

    The QBuffer is parented to the movie so it lives exactly as long as the
    movie does — no dangling device, no /tmp file.
    """
    movie = QtGui.QMovie()
    buffer = QtCore.QBuffer(movie)
    buffer.setData(gif_data)
    buffer.open(QtCore.QIODevice.OpenModeFlag.ReadOnly)
    movie.setDevice(buffer)
    movie.setFormat(b"GIF")
    movie.setCacheMode(QtGui.QMovie.CacheMode.CacheAll)
    return movie


def parse_gif_frame_delays(gif_data: bytes) -> list[int]:
    """
    Parse GIF bytes using Pillow to extract frame delays.
    Returns list of delays in milliseconds.
    """
    try:
        try:
            from PIL import Image
        except ImportError:
            logger.warning("Pillow not available, falling back to manual parsing")
            return []

        img = Image.open(io.BytesIO(gif_data))
        if not hasattr(img, 'n_frames'):
            return []

        delays = []
        for i in range(img.n_frames):
            img.seek(i)
            # Get duration in milliseconds, default to 100ms if not specified
            duration_ms = img.info.get('duration', 100)
            delays.append(duration_ms)

        img.close()
        logger.info(f"Calculated GIF duration: {sum(delays)/1000:.2f}s from {len(delays)} frames")
        return delays

    except Exception as e:
        logger.debug(f"Could not parse GIF frame delays with Pillow: {e}")
        return []


def get_gif_duration(movie: QtGui.QMovie, gif_data: bytes) -> tuple[float, list[int]]:
    """
    Calculate total duration of GIF animation in seconds and get frame delays.
    Returns: (total_duration_seconds, list_of_frame_delays_ms)
    """
    try:
        # Parse actual delays from the in-memory GIF bytes
        delays = parse_gif_frame_delays(gif_data)
        if delays:
            total_duration = sum(delays) / 1000.0
            return total_duration, delays

        # Fallback: estimate based on frame count
        frame_count = movie.frameCount()
        if frame_count > 0:
            estimated_duration = frame_count * 0.1  # Default 100ms per frame
            estimated_delays = [100] * frame_count
            logger.debug(f"Using estimated duration: {frame_count} frames * 0.1s = {estimated_duration:.2f}s")
            return estimated_duration, estimated_delays
        
        return 0.0, []
    except Exception as e:
        logger.debug(f"Could not calculate GIF duration: {e}")
        return 0.0, []


def scale_pixmap_if_needed(pixmap: QtGui.QPixmap, max_width: int, max_height: int) -> QtGui.QPixmap:
    """
    Scale pixmap down if needed, maintaining aspect ratio.
    If image is larger than max_width or max_height, scale it down.
    Does not scale up smaller images.
    Returns the scaled pixmap.
    """
    original_width = pixmap.width()
    original_height = pixmap.height()
    
    # Calculate scale factors for both dimensions
    width_scale = 1.0
    height_scale = 1.0
    
    if original_width > max_width:
        width_scale = max_width / original_width
    if original_height > max_height:
        height_scale = max_height / original_height
    
    # Use the smaller scale factor to ensure both constraints are met
    scale_factor = min(width_scale, height_scale)
    
    # Only scale if needed
    if scale_factor < 1.0:
        new_width = int(original_width * scale_factor)
        new_height = int(original_height * scale_factor)
        
        return pixmap.scaled(
            new_width, new_height,
            QtCore.Qt.AspectRatioMode.KeepAspectRatio,
            QtCore.Qt.TransformationMode.SmoothTransformation
        )
    
    return pixmap


def harden_pixmap(pixmap: QtGui.QPixmap, threshold: int = 128) -> QtGui.QPixmap:
    """Snap alpha to 0/255 so a smooth-scaled silhouette has a crisp edge that
    matches the 1-bit shape mask — otherwise the anti-aliased edge renders as a
    muddy fringe on X11 without a compositor.

    Uses Pillow's C-speed ``point`` on the alpha channel — a Python per-pixel
    loop here froze loads of large multi-frame chars (e.g. girl*, 120
    frames at 281×500)."""
    from PIL import Image

    image = pixmap.toImage().convertToFormat(QtGui.QImage.Format.Format_RGBA8888)
    width, height = image.width(), image.height()
    pil = Image.frombytes("RGBA", (width, height), image.constBits().tobytes())
    pil.putalpha(pil.getchannel("A").point(lambda value: 255 if value >= threshold else 0))
    hardened = QtGui.QImage(pil.tobytes("raw", "RGBA"), width, height,
                            QtGui.QImage.Format.Format_RGBA8888)
    return QtGui.QPixmap.fromImage(hardened.copy())
