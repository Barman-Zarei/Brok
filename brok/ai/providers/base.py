"""AIProvider interface. The UI and agent never talk to a vendor API directly."""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from typing import Iterator

from ..messages import Message, StreamEvent, ToolSchema
from ..transport import Transport


class AIProvider(ABC):
    name = "base"
    #: True when no data leaves the machine (Ollama on localhost). Drives the LOCAL/CLOUD badge.
    is_local = False
    supports_tools = True
    supports_vision = False

    def __init__(self, model: str, transport: Transport | None = None) -> None:
        from ..transport import UrllibTransport

        self.model = model
        self.transport = transport or UrllibTransport()

    @property
    def badge(self) -> str:
        return "LOCAL AI" if self.is_local else "CLOUD AI"

    @abstractmethod
    def chat(
        self,
        messages: list[Message],
        system: str = "",
        tools: list[ToolSchema] | None = None,
        cancel: threading.Event | None = None,
    ) -> Iterator[StreamEvent]:
        """Stream events; the last event is always ``done`` unless cancelled."""

    @abstractmethod
    def list_models(self) -> list[str]: ...

    def test_connection(self) -> str:
        """Return a short status string, raise ProviderError when unreachable."""
        models = self.list_models()
        return f"{self.name}: OK ({len(models)} models)"
