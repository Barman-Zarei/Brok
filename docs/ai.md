# AI providers

`AIProvider.chat(messages, system, tools, cancel)` streams `StreamEvent`s (`text`, `tool_call`, `done`).

| Provider | Class | Local? | Key |
|---|---|---|---|
| Claude | `ClaudeProvider` | no (CLOUD AI) | `ANTHROPIC_API_KEY` or OS keyring |
| Ollama | `OllamaProvider` | yes if host is localhost (LOCAL AI) | none |
| OpenAI / compatible | `OpenAIProvider` | no | `OPENAI_API_KEY` |

Add one: subclass `AIProvider`, register it in `brok/ai/providers/__init__.py:PROVIDERS` (or from a plugin).

**Orchestrator**: ordered chain `primary + fallbacks`; `local_only` removes every non-local provider (and
network tools). If a provider fails *before* output, the next one is tried; after partial output the error is
raised instead of silently switching model. Modes: CHAT, CODING, DEBUG, RESEARCH, VISION, VOICE, AUTOMATION,
LEARNING (selected by `/command` or inferred from the text, including Persian keywords).

Vision: `Message.images` is mapped to each provider's image format (Claude, Ollama, OpenAI).
Model names are configuration (`ai.claude_model` etc.), not hard-coded behaviour.
