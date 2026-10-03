"""Central AI orchestration: provider choice, fallback, local-only, cancellation."""

from __future__ import annotations

import logging
import threading
from typing import Callable, Iterator

from .messages import Message, StreamEvent, ToolSchema
from .personality import MODES, Personality
from .providers.base import AIProvider
from .transport import ProviderError

logger = logging.getLogger(__name__)

_CODE_HINTS = (
    "def ",
    "class ",
    "traceback",
    "error:",
    "exception",
    "import ",
    "```",
    "bug",
    "fix",
    "test",
    "کد",
    "ارور",
    "باگ",
    "تابع",
    "تست",
    "خطا",
)


def infer_mode(text: str, has_images: bool = False) -> str:
    low = text.lower()
    if has_images:
        return "VISION"
    if "traceback" in low or "error" in low or "ارور" in low or "باگ" in low:
        return "DEBUG"
    if any(h in low for h in _CODE_HINTS):
        return "CODING"
    if any(w in low for w in ("یادم بده", "teach me", "learn")):
        return "LEARNING"
    return "CHAT"


class AIOrchestrator:
    """Holds an ordered provider chain. The UI/agent only ever calls :meth:`stream`."""

    def __init__(
        self,
        providers: dict[str, AIProvider],
        primary: str,
        fallbacks: list[str] | None = None,
        local_only: bool = False,
        personality: Personality | None = None,
        on_send: Callable[[str, bool, int], None] | None = None,
    ) -> None:
        self.providers = providers
        self.primary = primary
        self.fallbacks = list(fallbacks or [])
        self.local_only = local_only
        self.personality = personality or Personality()
        self.on_send = on_send  # privacy hook: (provider, is_local, chars_sent)
        self._cancel = threading.Event()
        self.last_provider: AIProvider | None = None

    def chain(self) -> list[AIProvider]:
        names = [self.primary] + [n for n in self.fallbacks if n != self.primary]
        out = [self.providers[n] for n in names if n in self.providers]
        if self.local_only:
            out = [p for p in out if p.is_local]
        return out

    def cancel(self) -> None:
        self._cancel.set()

    def stream(
        self, messages: list[Message], mode: str = "CHAT", tools: list[ToolSchema] | None = None, language: str = ""
    ) -> Iterator[StreamEvent]:
        self._cancel.clear()
        mode = mode.upper() if mode.upper() in MODES else "CHAT"
        system = self.personality.system_prompt(mode, language)
        chain = self.chain()
        if not chain:
            hint = " (local-only mode is on: only a local Ollama provider is allowed)" if self.local_only else ""
            raise ProviderError("No AI provider is available" + hint + ".", retryable=False)
        last_exc: Exception | None = None
        for prov in chain:
            if tools and not prov.supports_tools:
                continue
            started = False
            try:
                if self.on_send:
                    self.on_send(prov.name, prov.is_local, sum(len(m.content) for m in messages) + len(system))
                self.last_provider = prov
                for ev in prov.chat(messages, system, tools, self._cancel):
                    started = True
                    yield ev
                    if self._cancel.is_set():
                        return
                return
            except ProviderError as exc:
                logger.warning("provider %s failed: %s", prov.name, exc)
                last_exc = exc
                if started:  # partial output already shown: do not silently switch model mid-answer
                    raise
        raise ProviderError(f"All AI providers failed. Last error: {last_exc}", retryable=False)
