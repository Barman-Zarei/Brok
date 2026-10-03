from __future__ import annotations

import json
import os
from typing import Callable, Iterator

from ..messages import Message, StreamEvent, ToolCall, ToolSchema
from ..transport import ProviderError
from .base import AIProvider

API_URL = "https://api.anthropic.com"
API_VERSION = "2023-06-01"
DEFAULT_MODEL = "claude-sonnet-5-5"


class ClaudeProvider(AIProvider):
    """Anthropic Messages API with streaming, tool use and image input.

    The key is resolved lazily (env ``ANTHROPIC_API_KEY`` or a ``key_resolver``,
    e.g. the OS keyring) and is never stored on disk or logged by this class.
    """

    name = "claude"
    is_local = False
    supports_vision = True

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        key_resolver: Callable[[], str] | None = None,
        base_url: str = API_URL,
        max_tokens: int = 4096,
        transport=None,
    ) -> None:
        super().__init__(model, transport)
        self._resolver = key_resolver
        self.base_url = base_url.rstrip("/")
        self.max_tokens = max_tokens

    def _key(self) -> str:
        key = (self._resolver() if self._resolver else "") or os.environ.get("ANTHROPIC_API_KEY", "")
        if not key:
            raise ProviderError(
                "Claude API key missing: set ANTHROPIC_API_KEY or store it in the keyring.", retryable=False
            )
        return key

    def _headers(self) -> dict[str, str]:
        return {"x-api-key": self._key(), "anthropic-version": API_VERSION}

    def list_models(self) -> list[str]:
        data = self.transport.get_json(f"{self.base_url}/v1/models?limit=100", self._headers())
        return [m["id"] for m in data.get("data", [])]

    @staticmethod
    def _convert(messages: list[Message]) -> list:
        out: list = []

        def push(role: str, blocks: list) -> None:
            if out and out[-1]["role"] == role:
                out[-1]["content"].extend(blocks)
            else:
                out.append({"role": role, "content": blocks})

        for m in messages:
            if m.role == "tool":
                push("user", [{"type": "tool_result", "tool_use_id": m.tool_call_id, "content": m.content}])
            elif m.role == "assistant":
                blocks: list = [{"type": "text", "text": m.content}] if m.content else []
                blocks += [{"type": "tool_use", "id": c.id, "name": c.name, "input": c.arguments} for c in m.tool_calls]
                if blocks:
                    push("assistant", blocks)
            else:
                blocks = [
                    {"type": "image", "source": {"type": "base64", "media_type": i.media_type, "data": i.data}}
                    for i in m.images
                ]
                blocks.append({"type": "text", "text": m.content})
                push("user", blocks)
        return out

    def chat(self, messages, system="", tools: list[ToolSchema] | None = None, cancel=None) -> Iterator[StreamEvent]:
        body: dict = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "stream": True,
            "messages": self._convert(messages),
        }
        if system:
            body["system"] = system
        if tools:
            body["tools"] = [
                {"name": t.name, "description": t.description, "input_schema": t.parameters} for t in tools
            ]
        blocks: dict[int, dict] = {}
        stop = "stop"
        for line in self.transport.stream_lines(f"{self.base_url}/v1/messages", self._headers(), body, cancel):
            if not line.startswith("data:"):
                continue
            try:
                ev = json.loads(line[5:].strip())
            except ValueError:
                continue
            t = ev.get("type")
            if t == "error":
                raise ProviderError("Claude: " + str(ev.get("error", {}).get("message", "unknown error")))
            if t == "content_block_start":
                cb = ev.get("content_block", {})
                if cb.get("type") == "tool_use":
                    blocks[ev["index"]] = {"id": cb["id"], "name": cb["name"], "json": ""}
            elif t == "content_block_delta":
                d = ev.get("delta", {})
                if d.get("type") == "text_delta":
                    yield StreamEvent("text", text=d.get("text", ""))
                elif d.get("type") == "input_json_delta" and ev["index"] in blocks:
                    blocks[ev["index"]]["json"] += d.get("partial_json", "")
            elif t == "content_block_stop" and ev.get("index") in blocks:
                b = blocks.pop(ev["index"])
                try:
                    args = json.loads(b["json"]) if b["json"] else {}
                except ValueError:
                    args = {}
                yield StreamEvent("tool_call", tool_call=ToolCall(b["id"], b["name"], args))
            elif t == "message_delta":
                stop = ev.get("delta", {}).get("stop_reason") or stop
            elif t == "message_stop":
                break
        yield StreamEvent("done", stop_reason=stop)
