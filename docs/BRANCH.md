# Branch `ANDROID` — Android (APK via GitHub Actions)

Builds an Android app with Qt's `pyside6-android-deploy` (Technical Preview, Linux host) in the workflow
`.github/workflows/build-android.yml` (manual run: Actions → *Build Android APK* → Run workflow).

## What you get
A regular **full-screen app** that opens Brok's workspace (AI chat, project files, diff and approvals) on a private
folder inside the app's storage (`brok/mobile.py`, entry `main.py`). Default profile: `low-end`.

## What is NOT possible / not included
- **The floating avatar over other apps.** Android needs the "draw over other apps" permission and Java code for
  that; a normal Qt window cannot do it. Hotkey, desktop tray and X11 activity counters do not exist on Android.
- Ollama does not run on a phone: use a cloud provider key, or point `BROK_OLLAMA_HOST` at a computer on your network.

## Honest status
- Verified here: the mobile entry point starts and quits headless **with Pillow/pynput/Xlib/psutil blocked**
  (`tests/test_mobile.py`), the deploy tool's flags match PySide6 6.11.2's `--help`, the workflow YAML parses.
- Checked against the real tool (not guessed): Qt's Android wheels live on `download.qt.io/official_releases/QtForPython`
  (cp311, `android_aarch64`), the tool downloads its own NDK (r27c for 6.11; the old pinned r26b was wrong), it needs a
  root `main.py`, it only reads `buildozer.spec` on the 2nd run (so the workflow adds data extensions + INTERNET), and it
  exits 0 even when it fails (the workflow checks for an `.apk`/`.aab`).
- **Never run:** the workflow itself, the APK, any device. Expect to iterate on the first run and send the failing log.
- The APK contains Python + PySide6 only (`requirements = python3,shiboken6,PySide6`): Pillow and other third-party
  packages are not bundled, and the mobile entry point does not need them.
- Config lives in the app's private dir (`ANDROID_PRIVATE`), or `BROK_CONFIG_DIR` if set.
