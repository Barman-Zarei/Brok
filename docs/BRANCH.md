# Branch `OFFLINE` — fully local

Default profile `offline`: AI is forced to **Ollama only** (`local_only`, cloud providers never used, even if a config file asks for them), no update check. Web search and GitHub/calendar features stay opt-in as always and are off by default.

Needs Ollama running locally (`ollama serve`, `ollama pull llama3.1`).

Built into OS-specific files by `.github/workflows/build-all.yml` (Actions → run → Artifacts).
The main line of development is `brok-migration`; this branch is kept in sync by merging it.
