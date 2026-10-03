"""Claude (Anthropic) chat backend for the desktop chat window; thin adapter over brok.ai.ClaudeProvider."""

from __future__ import annotations

from .ai.messages import Message
from .ai.providers.claude import ClaudeProvider
from .ai.transport import ProviderError, UrllibTransport


def _provider(base_url: str, api_key: str, model: str, timeout: float) -> ClaudeProvider:
    return ClaudeProvider(model=model, key_resolver=lambda: api_key, base_url=base_url or "https://api.anthropic.com",
                          transport=UrllibTransport(timeout))


def fetch_models(base_url: str, api_key: str, timeout: float) -> list[str]:
    try:
        return _provider(base_url, api_key, "", timeout).list_models()
    except ProviderError as exc:
        raise RuntimeError(str(exc)) from exc


class ClaudeBackend:
    def __init__(self, *, base_url: str, api_key: str, model: str, timeout: float) -> None:
        self.provider = _provider(base_url, api_key, model, timeout)

    def reply(self, user_text: str, system_prompt: str) -> str:
        try:
            events = self.provider.chat([Message("user", user_text)], system_prompt)
            text = "".join(e.text for e in events if e.kind == "text")
        except ProviderError as exc:
            raise RuntimeError(str(exc)) from exc
        if not text:
            raise RuntimeError("Claude returned an empty reply")
        return text
