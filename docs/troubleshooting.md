# Troubleshooting

- `brok-agent doctor` shows which providers are reachable.
- "Claude API key missing": set `ANTHROPIC_API_KEY` or enter the key in LLM… settings.
- Ollama unreachable: run `ollama serve`; check `BROK_OLLAMA_HOST`.
- Global hotkey "unavailable": needs pynput + X11/Windows/macOS permissions; use the tray icon instead.
- No voice: install `espeak-ng` (Linux) for Persian TTS; speech-to-text needs a configured `CommandSTT` template.
- Linux key/click counting off on Wayland: unchanged upstream limitation.

## Global hotkey is "unavailable"
On Linux the hotkey needs `pynput` (opt-in because it pulls `evdev`): `pip install "brok[hotkey]"`. On Wayland global key
capture is restricted by the compositor; use the tray icon or `/` commands in the chat instead.
