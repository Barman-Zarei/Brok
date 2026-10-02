# Brok Baseline (Phase 0/1) — audit of upstream myCat v0.1.37

Source: https://github.com/yumiaura/myCat (287 commits). Audited in a Linux sandbox, Python 3.12.3.

## Architecture
- Single package `mycat/`, ~37 top-level definitions in `main.py` (2447 lines, god-module: window, overlay, tray, wiring).
- Stack: PySide6>=6.10, Pillow>=12, pynput (Win/mac) / python-xlib (Linux). Extras: `secure` (keyring), `calendar` (icalendar).
- Features: draggable always-on-top character, char packs (zip), reminders, activity diary + key heatmap, focus, GitHub notifications, ICS calendar, shop, updater, localization (en/ko/ru/zh), speech bubbles.
- AI today: `llm_vendors.py` (Ollama + OpenAI-compatible chat, env/keyring keys), `llm_ui.py` (ChatDialog, LLMWorker QRunnable), `ai_backends.py` (image generation only: OpenAI/A1111/ComfyUI). **No Claude provider, no tools, no agent, no memory, no Persian locale.**
- CI: ci.yml, publish, AppImage/deb/snap/binary release workflows. Docker + PyInstaller spec present.

## Baseline results
| Check | Result |
|---|---|
| Install (`pip install -e .`) | OK |
| Tests (`pytest --forked`) | 313 passed, **3 failed** |
| Ruff | All checks passed |
| mypy | configured `strict`, not run yet |

Known failures: `tests/test_calendar_ics.py` x3 — `ModuleNotFoundError: icalendar` (optional `[calendar]` extra not installed; environment issue, not a code bug).
Not yet verified: GUI launch (needs display; offscreen only), Windows/macOS behavior, mypy.

## License / attribution (must preserve)
`LICENSE.txt` is a custom "MIT CAT LICENSE (Meow-IT)", copyright (c) 2025 @yumicabrera. Its notice must remain in all copies. Brok must keep it and add a NOTICE crediting upstream.

## Brand occurrence census (108 files)
`mycat` ~1058, `yumiaura` 177, `Desktop Cat` 5. Needs classification into: package/import names, config paths, UI strings, URLs, attribution (keep). Not a blind replace.
