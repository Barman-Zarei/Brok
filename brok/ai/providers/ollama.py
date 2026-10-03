from __future__ import annotations

import json
from typing import Iterator
from urllib.parse import urlparse

from ..messages import Message, StreamEvent, ToolCall, ToolSchema
from ..transport import ProviderError
from .base import AIProvider


class OllamaProvider(AIProvider):
    name = "ollama"
    supports_vision = True

    def __init__(self, model: str = "llama3.1", host: str = "http://127.0.0.1:11434", transport=None) -> None:
        super().__init__(model, transport)
        self.host = host.rstrip("/")

    @property
    def is_local(self) -> bool:  # type: ignore[override]
        host = urlparse(self.host).hostname or ""
        return host in ("127.0.0.1", "localhost", "::1")

    def list_models(self) -> list[str]:
        data = self.transport.get_json(f"{self.host}/api/tags", {})
        return [m["name"] for m in data.get("models", [])]

    @staticmethod
    def _convert(messages: list[Message], system: str) -> list:
        out: list = [{"role": "system", "content": system}] if system else []
        for m in messages:
            item: dict = {"role": m.role, "content": m.content}
            if m.images:
                item["images"] = [i.data for i in m.images]
            if m.tool_calls:
                item["tool_calls"] = [{"function": {"name": c.name, "arguments": c.arguments}} for c in m.tool_calls]
            out.append(item)
        return out

    def chat(self, messages, system="", tools: list[ToolSchema] | None = None, cancel=None) -> Iterator[StreamEvent]:
        body: dict = {"model": self.model, "messages": self._convert(messages, system), "stream": True}
        if tools:
            body["tools"] = [
                {
                    "type": "function",
                    "function": {"name": t.name, "description": t.description, "parameters": t.parameters},
                }
                for t in tools
            ]
        n = 0
        for line in self.transport.stream_lines(f"{self.host}/api/chat", {}, body, cancel):
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            if obj.get("error"):
                raise ProviderError(f"Ollama: {obj['error']}", retryable=False)
            msg = obj.get("message") or {}
            if msg.get("content"):
                yield StreamEvent("text", text=msg["content"])
            for tc in msg.get("tool_calls") or []:
                fn = tc.get("function", {})
                args = fn.get("arguments") or {}
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except ValueError:
                        args = {}
                n += 1
                yield StreamEvent("tool_call", tool_call=ToolCall(f"ollama-{n}", fn.get("name", ""), args))
            if obj.get("done"):
                yield StreamEvent("done", stop_reason="tool_use" if n else obj.get("done_reason", "stop"))
                return
