# Privacy

`brok-agent privacy` and `brok.privacy.PrivacyTracker` report: active provider, LOCAL/CLOUD, number of requests,
characters sent to cloud providers, project files read by the agent, memory counts, permission settings.
Local-only mode (`BROK_LOCAL_ONLY=1` / `ai.local_only`) removes cloud providers and network tools.
Memory (`~/.config/brok/memory.json`, mode 600) is viewable/editable/deletable (`brok-agent memory …`) and never
stores secrets. Existing myCat features (activity diary, key counts) are unchanged: local only, opt-in.
