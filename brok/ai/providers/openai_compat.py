from __future__ import annotations

import itertools
import json
import os
import threading
from typing import Any, Callable, Iterator

from ..messages import Message, StreamEvent, ToolCall, ToolSchema, parse_tool_args
from ..transport import ProviderError, Transport
from .base import AIProvider


class OpenAIProvider(AIProvider):
    """OpenAI Chat Completions; also works for any OpenAI-compatible endpoint."""

    name = "openai"
    supports_vision = True

    def __init__(
        self,
        model: str = "gpt-4o-mini",
        base_url: str = "https://api.openai.com/v1",
        key_resolver: Callable[[], str] | None = None,
        key_env: str = "OPENAI_API_KEY",
        transport: Transport | None = None,
    ) -> None:
        super().__init__(model, transport)
        self.base_url = base_url.rstrip("/")
        self._resolver, self._key_env = key_resolver, key_env
        self._seq = itertools.count(1)  # fallback tool-call ids stay unique across turns

    def _headers(self) -> dict[str, str]:
        key = os.environ.get(self._key_env, "") or (self._resolver() if self._resolver else "")
        if not key:
            raise ProviderError(f"API key missing: set {self._key_env}.", retryable=False)
        return {"Authorization": f"Bearer {key}"}

    def list_models(self) -> list[str]:
        return [m["id"] for m in self.transport.get_json(f"{self.base_url}/models", self._headers()).get("data", [])]

    @staticmethod
    def _convert(messages: list[Message], system: str) -> list[Any]:
        out: list[Any] = [{"role": "system", "content": system}] if system else []
        for m in messages:
            if m.role == "tool":
                out.append({"role": "tool", "tool_call_id": m.tool_call_id, "content": m.content})
            elif m.role == "assistant":
                item: dict[str, Any] = {"role": "assistant", "content": m.content or None}
                if m.tool_calls:
                    item["tool_calls"] = [
                        {
                            "id": c.id,
                            "type": "function",
                            "function": {"name": c.name, "arguments": json.dumps(c.arguments)},
                        }
                        for c in m.tool_calls
                    ]
                out.append(item)
            elif m.images:
                parts: list[Any] = [{"type": "text", "text": m.content}]
                parts += [
                    {"type": "image_url", "image_url": {"url": f"data:{i.media_type};base64,{i.data}"}}
                    for i in m.images
                ]
                out.append({"role": "user", "content": parts})
            else:
                out.append({"role": "user", "content": m.content})
        return out

    def chat(
        self,
        messages: list[Message],
        system: str = "",
        tools: list[ToolSchema] | None = None,
        cancel: threading.Event | None = None,
    ) -> Iterator[StreamEvent]:
        body: dict[str, Any] = {"model": self.model, "messages": self._convert(messages, system), "stream": True}
        if tools:
            body["tools"] = [
                {
                    "type": "function",
                    "function": {"name": t.name, "description": t.description, "parameters": t.parameters},
                }
                for t in tools
            ]
        calls: dict[int, dict[str, Any]] = {}
        finish = "stop"
        finished = False
        for line in self.transport.stream_lines(f"{self.base_url}/chat/completions", self._headers(), body, cancel):
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if payload == "[DONE]":
                finished = True
                break
            try:
                ev = json.loads(payload)
            except ValueError:
                continue
            if ev.get("error"):
                err = ev["error"]
                raise ProviderError("OpenAI: " + str(err.get("message", err) if isinstance(err, dict) else err))
            for ch in ev.get("choices", []):
                d = ch.get("delta") or {}
                if d.get("content"):
                    yield StreamEvent("text", text=d["content"])
                for tc in d.get("tool_calls") or []:
                    slot = calls.setdefault(tc.get("index", 0), {"id": "", "name": "", "args": ""})
                    slot["id"] = tc.get("id") or slot["id"]
                    fn = tc.get("function", {})
                    slot["name"] = fn.get("name") or slot["name"]
                    slot["args"] += fn.get("arguments", "")
                if ch.get("finish_reason"):
                    finished = True
                finish = ch.get("finish_reason") or finish
        if not finished and not (cancel is not None and cancel.is_set()):
            raise ProviderError("The connection closed before the response was complete.")
        for i in sorted(calls):
            c = calls[i]
            call_id = c["id"] or f"call-{next(self._seq)}"
            yield StreamEvent("tool_call", tool_call=ToolCall(call_id, c["name"], parse_tool_args(c["args"])))
        yield StreamEvent("done", stop_reason="tool_use" if calls else finish)
