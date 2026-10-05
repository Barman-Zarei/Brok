# Branch `LEGACY` — older operating systems and older dependency versions

Targets the **oldest OS versions the pinned Qt supports** (Qt 6.6): macOS 11+ (`MACOSX_DEPLOYMENT_TARGET=11.0`), Windows 10+, Linux built on Ubuntu 22.04 (older glibc than `ubuntu-latest`). Pins `pyside6==6.6.3.1` and `pillow<11`; frozen builds use Python 3.9.

Not covered: Windows 7/8 (see branch `WIN7`).

Built into OS-specific files by `.github/workflows/build-all.yml` (Actions → run → Artifacts).
The main line of development is `brok-migration`; this branch is kept in sync by merging it.
