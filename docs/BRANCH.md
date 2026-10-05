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
- Verified here: the mobile entry point starts and quits headless (test `tests/test_mobile.py`), the deploy tool's
  flags match its `--help`, the workflow YAML parses.
- **Never run:** the workflow itself, the APK, any device. Qt's Android wheels are not on PyPI: put their URLs into
  the workflow inputs (or repository variables `PYSIDE_ANDROID_WHEEL_URL` / `SHIBOKEN_ANDROID_WHEEL_URL`). They
  must match the PySide6 version and Python version you choose. Expect to iterate on the first runs.
- Pure-Python dependencies work; packages with C extensions (Pillow) may need Android builds.

