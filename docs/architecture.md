# Brok architecture

```
brok/
├── main.py, *_ui.py        existing desktop overlay (BrokWindow: always-on-top avatar, reminders, activity…)
├── gif_utils.py display.py  GIF/pixmap helpers; X11/screen detection (split out of main.py)
├── instance.py tray.py      single-instance activation; system tray + desktop entry (split out of main.py)
├── quick.py                 quick-command routing for the chat bubble (/fix /code /search /privacy …)
├── privacy_ui.py            privacy dashboard window
├── avatar/                 states · engine (state machine) · manager (events→states) · renderer · themes · assets
├── ai/                     messages · transport · personality · orchestrator · providers/{claude,ollama,openai_compat}
├── agent/                  tools (registry+permissions) · builtin_tools · sandbox · workspace (jail) · project · index
│                           loop (bounded agent) · debugger · health · learning · diff
├── core.py                 BrokConfig → providers → orchestrator → tool registry (shared by GUI and CLI)
├── workspace_ui.py         coding workspace window
├── cli.py                  `brok-agent` terminal interface
├── config.py memory.py privacy.py commands.py plugins.py hotkey.py productivity.py
├── github_agent.py web/    GitHub REST + web research tools
└── voice/                  STT/TTS interfaces + pipeline
```

Rules: the UI never calls a vendor API; only `AIOrchestrator` does. Every action a model can take is a
`ToolSpec` with a risk level and confirmation rule, executed only through `ToolRegistry.execute`.
No Qt imports exist in `ai/`, `agent/`, `avatar/engine|states|manager`, `memory`, `config` (all unit-testable headless).

The desktop chat window (`llm_*.py`) is the original simple request/response chat; Claude was added there as a
vendor. The agent features (tools, diff approval, memory) live in the **coding workspace** and `brok-agent`.
