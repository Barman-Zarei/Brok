# Branch `PYTHON38` — Python 3.8 compatibility

Keeps full support for **Python 3.8** (the last interpreter for some older machines). The whole test suite passes on CPython 3.8.20.

Limits: PySide6 6.6.3.1 is the newest Qt build that installs on 3.8 (Windows 10+, macOS 11+). Frozen builds use Python 3.8, so the Apple Silicon job is dropped (no 3.8 on those runners): the Intel macOS build runs on Apple Silicon through Rosetta. The optional `openai` package is not bundled.

Built into OS-specific files by `.github/workflows/build-all.yml` (Actions → run → Artifacts).
The main line of development is `brok-migration`; this branch is kept in sync by merging it.
