# Privacy

`brok-agent privacy` and `brok.privacy.PrivacyTracker` report: active provider, LOCAL/CLOUD, number of requests,
characters sent to cloud providers, project files read by the agent, memory counts, permission settings.
Local-only mode (`BROK_LOCAL_ONLY=1` / `ai.local_only`) removes cloud providers and network tools.
Memory (`~/.config/brok/memory.json`, mode 600) is viewable/editable/deletable (`brok-agent memory …`) and never
stores secrets. Existing myCat features (activity diary, key counts) are unchanged: local only, opt-in.

## Privacy dashboard (GUI)
Right-click Brok (or the tray icon) → **Privacy…**, or type `/privacy` in the chat. It shows the active provider with a
green **LOCAL AI** / amber **CLOUD AI** badge, offline mode, AI requests and characters sent to the cloud this session,
the project files read for the AI, memory counts, permission toggles and which accounts have a credential configured
(names only — values are never displayed or logged). The same report is available in the terminal via
`brok-agent privacy`. Counters are per session and kept in memory only.
