# Python compatibility

**The main branch (`brok-migration`) requires Python 3.10 or newer** (CI runs 3.10, 3.11, 3.12, 3.13).

Older interpreters are served by dedicated branches, which share the code and are kept in sync by merging:

| Need | Branch | Status |
|---|---|---|
| Python 3.8 | `PYTHON38` | full test suite (438 tests) passes on CPython 3.8.20; PySide6 6.6.3.1 / Pillow 10.4 |
| Python 3.9 + pinned old dependencies | `LEGACY` | full suite passes on CPython 3.9.25 with `pyside6==6.6.3.1`, `pillow<11` |
| Windows 7 (Python 3.8, Qt 5.15 / PySide2) | `WIN7` | suite passes on Linux with PySide2; **not run on Windows 7** |

Why 3.10+ on main: Python 3.8/3.9 are end-of-life, and PySide6 releases newer than 6.6.3.1 no longer install on 3.8.
Shared code is still written to be 3.8-safe (`from __future__ import annotations`, no `match`), so merging into the
legacy branches stays easy; main may start using 3.10+ syntax when that is worth the divergence.

History: an earlier audit note claiming 3.8 was impossible was wrong and was corrected after actually testing.
