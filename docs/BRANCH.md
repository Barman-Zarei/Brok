# Branch `WIN7` — Windows 7 (Qt 5.15 / PySide2 / Python 3.8)

Qt 6 (PySide6) needs Windows 10+. This branch runs on **Qt 5.15 via PySide2 on Python 3.8**, the newest combination
that still targets Windows 7 SP1.

How it works: all of Brok is written against PySide6. `brok/qt5compat.py` registers PySide2 under the `PySide6`
name when PySide6 is not installed and adds the few Qt 6 APIs Brok uses that Qt 5 lacks (`QAction` in QtGui,
`exec()`, `QMouseEvent.position()`). On other branches/platforms it does nothing.

## What is verified
- The full test suite (437 tests) passes on **Linux, Python 3.8, PySide2 5.15.2.1** (offscreen Qt).
- A PyInstaller build of this branch starts headless on Linux (see build-all smoke test).

## What is NOT verified (honest status)
- **Nothing has been run on a real Windows 7 machine.** Qt 5.15 and CPython 3.8 support Windows 7 SP1, but the
  Windows 7 specifics (UCRT update KB2999226, Visual C++ 2015-2019 runtime, PyInstaller 5 bootloader) are untested.
- Window transparency/always-on-top behaviour with the Windows 7 Aero/Basic themes is untested.
- Python 3.9+ is not supported here (PySide2 5.15.2.1 wheels stop at 3.10, and Windows 7 stops at 3.8).

## Build
`build-all.yml` produces `brok-WIN7-windows-x64.exe` (Python 3.8, `pyinstaller<6`) and a Linux binary used as a
smoke test. Install from source on Windows 7: `py -3.8 -m pip install .[calendar]` then `brok`.
