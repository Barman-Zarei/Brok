# Branch `IOS` — iOS / iPadOS (Xcode project via GitHub Actions)

Prepares an iOS build with Qt 6.12+'s PySide6 iOS tooling in `.github/workflows/build-ios.yml`
(manual run: Actions → *Build iOS* → Run workflow) on a macOS runner.

## What the workflow does
1. Installs Qt (macOS host + iOS) with aqtinstall and cross-compiles PySide6 for `ios_arm64`
   (`tools/cross_compile_ios/main.py build`, per Qt's blog post).
2. If a hand-written `pyside6-ios.toml` is present in the repository root: generates the Xcode project and builds an
   **unsigned** archive. Without that file this step is skipped with a notice.
3. Uploads what it produced.

## What you must do yourself
- Write `pyside6-ios.toml` (Qt: no generator yet).
- An **Apple Developer account** (paid) and signing to install on a device or ship to the App Store. Nothing here
  signs or uploads anything.

## What is NOT possible / not included
- The floating avatar (iOS has no overlay windows). The app is a normal full-screen app opening the workspace
  (`brok/mobile.py`, `main.py`). No hotkey, tray or X11 counters.
- Per Qt: no third-party C-extension wheels on iOS (Pillow), no iOS Simulator yet.

## Honest status
Verified here: the entry point starts headless, the workflow YAML parses. **Never run:** the workflow, the Xcode
project, any device. Whether Qt 6.12 is published for aqtinstall at your run time is unchecked.

