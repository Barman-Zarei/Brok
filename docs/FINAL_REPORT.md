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
Upstream baseline: 313 passed / 3 env failures. Now: **400 passed on Python 3.8.20 and 3.12.3**, ruff clean,
wheel/sdist build OK on 3.8, GUI starts offscreen without errors.

## NOT verified / not built (be aware)
- Real network calls: Claude, OpenAI, Ollama, GitHub, Brave were tested only against fake transports (request/stream
  formats follow each public API but have not been exercised with live keys).
- Windows and macOS: not run. Real display GUI: only the offscreen Qt platform was used; visuals checked via rendered images.
- Speech-to-text: interface + command wrapper only (no bundled engine). Text-to-speech uses OS engines (espeak-ng/say/SAPI), untested here.
- Global hotkey: manager exists and degrades gracefully; it is not yet wired into main.py's tray/startup.
- Vision: providers accept images; there is no screenshot-capture or image-attach button in the UI yet.
- Memory: the store, CLI and agent-prompt injection exist; the desktop chat window does not read/write it yet.
- Agent features (tools/diff/memory) live in the workspace and CLI; the simple desktop chat bubble is still plain chat.
- mypy strict (configured upstream) was not run/clean; the learning/debug/health tools are driven through the agent (CLI) rather than dedicated GUI panels.
- Command sandbox is pattern-based, not an OS container. Health report is heuristic.
- Persian translation is machine-quality, written by an AI; have a native speaker review it.
- README translations (RU/CN/KO/ID) are pre-Brok cat-era text with a warning banner.

## How to run
`pip install .` → `brok` (GUI) · `brok-agent --project . ask "..."` · `brok-agent doctor`.
Claude: `export ANTHROPIC_API_KEY=...` (or LLM… dialog). Ollama: `ollama serve && ollama pull llama3.1`.
Python 3.8 note: PySide6 6.6.3.1 and Pillow 10.4 are the newest wheels for 3.8 (pip picks them automatically).

## Git
Branch `brok-migration`; remote `origin` = https://github.com/Barman-Zarei/Brok.git, `upstream` = yumiaura/myCat.
Push: `git push -u origin brok-migration` (needs your GitHub login; I could not push).

## Roadmap
Wire hotkey + memory into the chat bubble · screenshot capture · bundled STT (whisper.cpp) · real-key integration tests ·
Windows/macOS CI builds · vector search behind `ProjectIndex.retrieve` · avatar pack marketplace · multi-agent.
