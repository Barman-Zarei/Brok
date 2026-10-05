"""Build/runtime profiles.

One codebase, several flavours (low-end PCs, offline, no-GPU, ...). A branch of the repository changes
``DEFAULT_PROFILE`` and its packaging; users can still pick a profile at run time with ``BROK_PROFILE=<name>``.
A profile only changes things that really exist: render backend, UI tick rate, background network checks and AI
defaults. It never adds features.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

DEFAULT_PROFILE = "standard"  # the only line that differs between branches' runtime behaviour


@dataclass(frozen=True)
class Profile:
    name: str
    description: str
    tick_ms: int = 33  # avatar repaint timer (33 ms ≈ 30 fps)
    check_updates: bool = True  # background "new version?" request at start-up
    software_render: bool = False  # force Qt's CPU renderer (machines without a usable GPU)
    local_only: bool = False  # never use cloud AI providers
    debug_logging: bool = False


PROFILES = {
    p.name: p
    for p in (
        Profile("standard", "Default behaviour."),
        Profile("lite", "Same runtime as standard; the branch ships a smaller package."),
        Profile("low-end", "Weak CPUs/RAM: ~15 fps avatar, no start-up update check.", tick_ms=66, check_updates=False),
        Profile("no-gpu", "No usable GPU: Qt software rendering.", software_render=True),
        Profile(
            "offline",
            "Fully local: Ollama only, cloud providers disabled, no update check.",
            check_updates=False,
            local_only=True,
        ),
        Profile("experimental", "Staging area for unstable work: verbose logging.", debug_logging=True),
    )
}


def active() -> Profile:
    """The profile in effect: ``BROK_PROFILE`` if it names a known one, else the branch default."""
    name = os.environ.get("BROK_PROFILE", "").strip().lower() or DEFAULT_PROFILE
    prof = PROFILES.get(name)
    if prof is None:
        logging.getLogger(__name__).warning("unknown BROK_PROFILE %r; using %r", name, DEFAULT_PROFILE)
        prof = PROFILES[DEFAULT_PROFILE]
    return prof


def apply_environment(prof: Profile | None = None) -> None:
    """Set process env vars the profile needs. Call before the QApplication is created."""
    prof = prof or active()
    if prof.software_render:
        for key, value in (
            ("QT_OPENGL", "software"),
            ("QT_QUICK_BACKEND", "software"),
            ("QT_XCB_FORCE_SOFTWARE_OPENGL", "1"),
            ("LIBGL_ALWAYS_SOFTWARE", "1"),
        ):
            os.environ.setdefault(key, value)
