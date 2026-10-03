# Configuration

`~/.config/brok/brok.json` (sections: ai, voice, avatar, memory, github, web, security, privacy, ui, notifications,
coding). Env overrides: `BROK_AI_PROVIDER`, `BROK_LOCAL_ONLY`, `BROK_CLAUDE_MODEL`, `BROK_OLLAMA_HOST`,
`BROK_OLLAMA_MODEL`, `BROK_LANGUAGE`, `BROK_HOTKEY`. Secrets: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GITHUB_TOKEN`,
`BRAVE_API_KEY` or the OS keyring (never written to brok.json).

Claude: `export ANTHROPIC_API_KEY=...` then `brok-agent doctor`, or GUI: right-click → LLM… → Claude (Anthropic).
Ollama: `ollama serve`, `ollama pull llama3.1`; defaults to http://127.0.0.1:11434.
Legacy `~/.config/mycat` is copied to `~/.config/brok` once, never deleted.
