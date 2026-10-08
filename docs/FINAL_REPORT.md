# Brok — final report

## Architecture summary
See docs/architecture.md. New headless core (`brok/ai`, `brok/agent`, `brok/avatar`, memory/config/privacy/plugins/voice/web)
plus Qt integration (coding workspace, Claude in the desktop chat, robot default char, RTL).

## Preserved from myCat
Overlay, always-on-top/drag, GIF chars + char packs, tray, reminders, activity diary/heatmap/focus, GitHub notifications,
ICS calendar, shop, updater, localization (en/ko/ru/zh), Ollama + OpenAI-compatible chat, AI char generator, Docker/packaging.

## New in Brok
Robot avatar (13 states, procedural, packs) · AIProvider abstraction (Claude/Ollama/OpenAI) + orchestrator (fallback,
local-only, cancel, privacy hook) · personality layer · BrokConfig · tool registry with risk/confirmation · command
sandbox · workspace jail · bounded agent loop · diff-first approval · project detection + index · git tools ·
GitHub REST tools · web search/fetch (SSRF-guarded) · memory (4 kinds, inspectable, secret-refusing) · privacy report ·
plugins · global-hotkey manager · quick commands · learning mode · AI debugger · health report · calculator/notes ·
voice interfaces + OS TTS + text fallback · image input for providers · Persian locale (278 strings) + RTL ·
coding workspace window · `brok-agent` CLI · Claude vendor in the desktop chat · Brok system prompt (was a sarcastic cat).

## Tests
Upstream baseline: 313 passed / 3 env failures. Now: **408 passed on Python 3.8.20 and 3.12.3**, ruff clean,
wheel/sdist build OK on 3.8, GUI starts offscreen without errors.

## Completed in round 2
Global hotkey wired into startup (default Ctrl+Space, signal-bridged to the GUI thread, degrades gracefully) ·
memory in the desktop chat (`/remember`, `/memory`, `/forget`, `/forget-all`; injected into the system prompt; refuses secrets) ·
vision in the workspace (attach image, screenshot; orchestrator never silently drops an image) ·
Assistants tab (AI debugger, learning mode, project health) · `mypy --strict` clean on all 48 new modules (also in CI) ·
README in RU/CN/KO/ID/FA rewritten for Brok · one real bug found by mypy and fixed (stale type-comment in the agent loop).

## NOT verified / not built (be aware)
- Real network calls: Claude, OpenAI, Ollama, GitHub, Brave were tested only against fake transports (formats follow each
  public API, but were never exercised with live keys). First thing to try: `brok-agent doctor`.
- Windows and macOS: not run. Real display GUI: only Qt's offscreen platform was used (visuals checked via rendered images).
  Screenshot capture may not work on Wayland.
- Global hotkey needs pynput (installed by default only on Windows/macOS in pyproject) and desktop permissions; on Linux it
  may report "unavailable" and the tray icon remains the way in.
- Speech-to-text: interface + command wrapper only (no bundled engine). Text-to-speech uses OS engines (espeak-ng/say/SAPI), untested here.
- The simple desktop chat bubble is plain chat (+ memory commands); tools/diff/agent features live in the coding workspace and `brok-agent`.
  Images are not sent from the chat bubble (only from the workspace).
- Command sandbox is pattern-based, not an OS container. Health report is heuristic, not a security audit.
- Persian translation (278 + ~45 UI strings) and the RU/CN/KO/ID READMEs were written by an AI; have native speakers review them.
- mypy strict covers the new modules only; the upstream myCat modules were not made strict-clean.

## How to run
`pip install .` → `brok` (GUI) · `brok-agent --project . ask "..."` · `brok-agent doctor`.
Claude: `export ANTHROPIC_API_KEY=...` (or LLM… dialog). Ollama: `ollama serve && ollama pull llama3.1`.
Python 3.8 note (WIN7 branch): PySide2 5.15.2.1 and Pillow 10.4 are used so the app runs on Windows 7.

## Git
Branch `brok-migration`; remote `origin` = https://github.com/Barman-Zarei/Brok.git, `upstream` = yumiaura/myCat.
Push: `git push -u origin brok-migration` (needs your GitHub login; I could not push).

## Roadmap
Wire hotkey + memory into the chat bubble · screenshot capture · bundled STT (whisper.cpp) · real-key integration tests ·
Windows/macOS CI builds · vector search behind `ProjectIndex.retrieve` · avatar pack marketplace · multi-agent.

## Completed in round 3
Privacy dashboard GUI (menu → Privacy…, `/privacy`) sharing one report with `brok-agent privacy` · quick commands routed in the
desktop chat (`brok/quick.py`; `/search` runs off the UI thread; `/code /git /github /test /run` open the workspace) ·
`main.py` split (2471 → ~1950 lines: `gif_utils`, `display`, `instance`, `tray`; old names re-exported) · `PixelCatWindow` →
`BrokWindow` (alias kept), demo renamed, cat wording removed from comments · ko/ru/zh locales now cover every English string
(test enforces it for all locales) · Whisper STT + microphone recorder behind `pip install "brok[voice]"` and a Speak button in the
workspace · `brok[hotkey]` extra with an install hint · CI mypy scope + docs updated.
Verified here: 422 tests pass on Python 3.12, ruff clean, mypy --strict clean on 50+ new modules, offscreen GUI start OK,
Python 3.8 *syntax* check of every file OK (a real 3.8 interpreter was not available this round).

## Completed in round 4
`BrokWindow` split into `DialogsMixin` / `UpdateMixin` / `GeometryMixin` (`main.py` 2471 → 1504 lines; behaviour unchanged,
tested) · **real Python 3.8.20 run: 425 passed** (also 425 on 3.12) · wheel + sdist build and `twine check` pass ·
GUI startup smoke test clean · CI gained a (non-blocking) Windows/macOS test job that has not been run yet.

## Still NOT done / not verified
- `mypy --strict` on the upstream modules (~480 errors; ~195 even in non-strict `--check-untyped-defs`) was not attempted.
- Chat bubble: no tool use / image sending (by design: use the workspace; the legacy chat backend is text-only).
- Whisper/microphone never ran with real audio; Claude/OpenAI/Ollama/GitHub/Brave never ran with live keys.
- Windows/macOS untested (CI job added, not yet run); no real display, only Qt offscreen; Wayland hotkey/screenshot limits.
- AI-written translations (fa/ru/zh/ko/id) need native review. Nothing pushed to GitHub.
