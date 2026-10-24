#!/usr/bin/env python3
"""In-app self-update for the prebuilt binaries.

Downloads this platform's asset from the latest GitHub release, swaps it in, and
relaunches. Source / pip installs are never modified — they only learn that a
newer version exists (the caller shows a message and a link). Everything is
fetched over HTTPS from the release's stable, version-less download URLs.

The GUI flow (menu action, confirm dialog, progress, relaunch) lives in
``main.py``; this module is pure logic so it stays testable.
"""

from __future__ import annotations

import logging
import os
import platform
import shlex
import stat
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)

RELEASE_DOWNLOAD = "https://github.com/Barman-Zarei/Brok/releases/latest/download"
RELEASES_PAGE = "https://github.com/Barman-Zarei/Brok/releases/latest"

# Windows CreateProcess flag: run the update swapper with a hidden console so no
# black window flashes up (and none lingers if the swap stalls).
CREATE_NO_WINDOW = 0x08000000


def install_kind() -> str:
    """How this instance was installed.

    One of ``source`` (running from a checkout or pip — nothing to swap),
    ``snap``, ``appimage``, ``deb``, ``macos`` or ``windows``.
    """
    if not getattr(sys, "frozen", False):
        return "source"
    if sys.platform == "darwin":
        return "macos"
    if sys.platform.startswith("win"):
        return "windows"
    # Frozen Linux: snapd sets SNAP to the mounted snap; an AppImage exports
    # APPIMAGE with the real .AppImage path; otherwise it's the binary installed
    # from the .deb (in /usr/bin).
    if os.environ.get("SNAP"):
        return "snap"
    if os.environ.get("APPIMAGE"):
        return "appimage"
    return "deb"


def can_self_update(kind: str) -> bool:
    """Kinds that download + swap + relaunch on their own. Only the Windows exe
    and macOS .app; pip/deb/AppImage/snap installs are only *told* an update
    exists (their package manager / a fresh download should apply it)."""
    return kind in ("macos", "windows")


def update_hint(kind: str) -> str:
    """A one-line 'how to update' for the kinds that don't self-update."""
    if kind == "snap":
        return "snap refresh brok"
    if kind == "deb":
        return "Download the new .deb from the releases page and install it."
    if kind == "appimage":
        return "Download the new AppImage from the releases page."
    if (Path(__file__).resolve().parent.parent / ".git").exists():
        return "git pull"
    return "pip install --upgrade brok"


def asset_name(kind: str) -> str:
    """Version-less release asset filename for this platform, or ``""``."""
    if kind == "windows":
        return "brok-windows-x64.exe"
    if kind == "macos":
        arch = platform.machine().lower()
        return "brok-macos-arm64.zip" if arch in ("arm64", "aarch64") else "brok-macos-x64.zip"
    if kind == "appimage":
        return "brok-linux-x86_64.AppImage"
    if kind == "deb":
        return "brok-linux-amd64.deb"
    return ""


def asset_url(kind: str) -> str:
    name = asset_name(kind)
    return f"{RELEASE_DOWNLOAD}/{name}" if name else ""


def make_executable(path: str) -> None:
    mode = os.stat(path).st_mode
    os.chmod(path, mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


DOWNLOAD_ATTEMPTS = 3


def download(url: str, dest: str, progress=None, attempts: int = DOWNLOAD_ATTEMPTS) -> None:
    """Stream ``url`` to ``dest``; call ``progress(done, total)`` as it goes.

    The data goes to ``dest + ".part"`` and is moved onto ``dest`` only once it is complete, so ``dest`` is never a
    half-written build (that produced a corrupt exe that died with "Failed to load Python DLL"): not after a failed
    attempt, not after the last failure, and not when ``progress`` raises to cancel. The finished file is verified
    against ``Content-Length`` and a truncated or interrupted transfer is retried. ``total`` is 0 when the server
    sends no Content-Length (then we can't verify, and take what we got). ``progress`` may raise to cancel; that is
    not a network error, so it propagates immediately instead of being retried.
    """
    if attempts < 1:
        raise ValueError("attempts must be at least 1")
    request = urllib.request.Request(url, headers={"User-Agent": "brok"})
    part = dest + ".part"
    last_error: OSError | None = None
    try:
        for attempt in range(1, attempts + 1):
            try:
                with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 - official HTTPS release URL
                    total = int(response.headers.get("Content-Length") or 0)
                    done = 0
                    with open(part, "wb") as out:
                        while True:
                            chunk = response.read(1 << 16)
                            if not chunk:
                                break
                            out.write(chunk)
                            done += len(chunk)
                            if progress is not None:
                                progress(done, total)
                if total and done != total:
                    raise OSError(f"incomplete download: got {done} of {total} bytes")
                os.replace(part, dest)
                return
            except OSError as error:  # network / truncation — retry, then give up
                last_error = error
                logger.warning("download attempt %d/%d failed: %s", attempt, attempts, error)
        assert last_error is not None  # attempts >= 1, so the loop ran and every pass failed
        raise last_error
    finally:
        try:
            os.remove(part)  # nothing half-written is ever left behind (no-op after a successful replace)
        except OSError:
            pass


def staging_path(kind: str) -> str:
    """Where to download the new build before swapping it in (temp dir)."""
    return os.path.join(tempfile.gettempdir(), asset_name(kind))


def apply_and_relaunch(kind: str, downloaded: str) -> None:
    """Swap in ``downloaded`` and spawn the new build. The caller must quit the
    app immediately afterwards so the old process exits."""
    if kind == "macos":
        apply_macos(downloaded)
    elif kind == "windows":
        apply_windows(downloaded)
    else:
        raise ValueError(f"cannot self-update install kind {kind!r}")


def macos_swap_script(pid: int, zip_path: str, app: str) -> str:
    """The /bin/sh helper that replaces ``app`` once ``pid`` has exited.

    The installed app is only touched after the new one was extracted and found; it is moved aside, not deleted, and
    put back if the copy fails, so a corrupt download can never leave the user with no app at all.
    """
    q = shlex.quote
    old = q(app + ".old")
    reopen = f"open {q(app)}"
    return (
        "#!/bin/sh\n"
        f"while kill -0 {pid} 2>/dev/null; do sleep 1; done\n"
        'tmp="$(mktemp -d)" || exit 1\n'
        f'/usr/bin/ditto -x -k {q(zip_path)} "$tmp" || {{ rm -rf "$tmp"; {reopen}; exit 1; }}\n'
        f'[ -d "$tmp/brok.app" ] || {{ rm -rf "$tmp"; {reopen}; exit 1; }}\n'
        f"rm -rf {old}\n"
        f'mv {q(app)} {old} || {{ rm -rf "$tmp"; {reopen}; exit 1; }}\n'
        f'if /usr/bin/ditto "$tmp/brok.app" {q(app)}; then rm -rf {old}; '
        f"else rm -rf {q(app)}; mv {old} {q(app)}; fi\n"
        f"/usr/bin/xattr -dr com.apple.quarantine {q(app)} 2>/dev/null\n"
        f"{reopen}\n"
        f'rm -rf "$tmp" {q(zip_path)} "$0"\n'
    )


def apply_macos(zip_path: str) -> None:
    # sys.executable is .../brok.app/Contents/MacOS/brok.
    app = os.path.dirname(os.path.dirname(os.path.dirname(sys.executable)))
    if not app.endswith(".app") or not os.path.isdir(app):
        # e.g. a bare onedir build: three levels up is NOT ours to replace.
        raise RuntimeError(f"cannot self-update: {app!r} is not a .app bundle")
    script = os.path.join(tempfile.gettempdir(), "brok-update.sh")
    with open(script, "w", encoding="utf-8") as handle:
        handle.write(macos_swap_script(os.getpid(), zip_path, app))
    make_executable(script)
    subprocess.Popen(["/bin/sh", script], start_new_session=True)  # noqa: S603
    logger.info("macOS update helper launched for %s", app)


def apply_windows(downloaded: str) -> None:
    exe = sys.executable
    pid = os.getpid()
    log = os.path.join(tempfile.gettempdir(), "brok-update.log")
    script = os.path.join(tempfile.gettempdir(), "brok-update.bat")
    for path in (downloaded, exe, log):
        # The swapper uses delayed expansion: % and ! in a path would be expanded and " would end the quoting.
        if any(ch in path for ch in '%!"'):
            raise RuntimeError(f'cannot self-update: the path {path!r} contains one of % ! " - update manually')
    # Wait for this process (and its bootloader) to exit and release the exe, then
    # KEEP RETRYING the overwrite: a onefile build stays locked for a moment after
    # the app PID is gone, so a single `move` right away fails and nothing
    # relaunches. Delays use `ping`, not `timeout`: the swapper's hidden console has
    # no interactive stdin, and `timeout` errors out ("input redirection is not
    # supported") without one — which was breaking the wait/retry loops entirely.
    body = (
        "@echo off\r\n"
        "setlocal enabledelayedexpansion\r\n"
        f'set "LOG={log}"\r\n'
        f'set "NEW={downloaded}"\r\n'
        f'set "EXE={exe}"\r\n'
        'echo swapper started %DATE% %TIME% > "%LOG%"\r\n'
        ":wait\r\n"
        f'tasklist /FI "PID eq {pid}" 2>nul | find "{pid}" >nul\r\n'
        "if not errorlevel 1 ( ping -n 2 127.0.0.1 >nul & goto wait )\r\n"
        'echo app exited >> "%LOG%"\r\n'
        "set /a TRIES=0\r\n"
        ":swap\r\n"
        'move /Y "%NEW%" "%EXE%" >nul 2>>"%LOG%"\r\n'
        "if not errorlevel 1 goto launch\r\n"
        "set /a TRIES+=1\r\n"
        'echo move attempt !TRIES! failed >> "%LOG%"\r\n'
        "if !TRIES! LSS 30 ( ping -n 2 127.0.0.1 >nul & goto swap )\r\n"
        'echo gave up swapping after !TRIES! tries >> "%LOG%"\r\n'
        ":launch\r\n"
        # Clear the PyInstaller onefile bootloader's private env vars before
        # relaunching. The swapper is a descendant of the old frozen process, so
        # the new exe would otherwise inherit these and the bootloader would think
        # it is the already-extracted second stage — looking for its DLLs in the
        # old (now deleted) _MEI dir and dying with "Failed to load Python DLL".
        # This is why the first auto-relaunch failed but a manual launch (clean
        # Explorer env) always worked.
        'set "_MEIPASS2="\r\n'
        'set "_PYI_ARCHIVE_FILE="\r\n'
        'set "_PYI_APPLICATION_HOME_DIR="\r\n'
        'set "_PYI_PARENT_PROCESS_LEVEL="\r\n'
        'set "_PYI_SPLASH_IPC="\r\n'
        'echo launching "%EXE%" >> "%LOG%"\r\n'
        'start "" "%EXE%"\r\n'
        'echo done >> "%LOG%"\r\n'
        'del "%~f0"\r\n'
    )
    with open(script, "w", encoding="utf-8") as handle:
        handle.write(body)
    # CREATE_NO_WINDOW: give the swapper a HIDDEN console. DETACHED_PROCESS (used
    # before) gives cmd no console at all, so every `ping`/`tasklist`/`find` it runs
    # made Windows allocate a fresh console — a black window that flashed up and,
    # when the swap stalled, sat there showing the wait loop. A hidden console the
    # child console tools reuse means nothing is ever visible. The swapper still
    # outlives this process (child processes aren't tied to the parent's lifetime).
    # Also hand the swapper an environment with the PyInstaller onefile vars
    # stripped, so the relaunched exe (our descendant) never inherits them and
    # extracts fresh — belt-and-suspenders with the `set ""` lines in the batch.
    clean_env = {
        key: value for key, value in os.environ.items() if not key.startswith("_PYI") and not key.startswith("_MEIPASS")
    }
    subprocess.Popen(  # noqa: S603
        ["cmd", "/c", script], creationflags=CREATE_NO_WINDOW, close_fds=True, env=clean_env
    )
    logger.info("Windows update swapper launched for %s (log: %s)", exe, log)


__all__ = [
    "install_kind",
    "can_self_update",
    "update_hint",
    "asset_name",
    "asset_url",
    "download",
    "staging_path",
    "apply_and_relaunch",
    "RELEASES_PAGE",
]
