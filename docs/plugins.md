# Plugins

Subclass `brok.plugins.Plugin`, implement `register(api)` and call `api.register_tool(ToolSpec(...))` /
`api.register_command(name, fn)`. Expose it via the entry-point group `brok.plugins`. Tools are namespaced
`<plugin>.<tool>` and can never be silent (risk floor MEDIUM). A failing plugin is isolated and logged.
Not implemented (interfaces only): Discord, Telegram, Notion, VS Code, JetBrains, Browser, Database, Docker, Cloud.
