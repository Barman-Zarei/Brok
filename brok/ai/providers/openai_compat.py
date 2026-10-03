from __future__ import annotations

import json
import os
from typing import Callable, Iterator

from ..messages import Message, StreamEvent, ToolCall, ToolSchema
from ..transport import ProviderError
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
        transport=None,
    ) -> None:
        super().__init__(model, transport)
        self.base_url = base_url.rstrip("/")
        self._resolver, self._key_env = key_resolver, key_env

    def _headers(self) -> dict[str, str]:
        key = os.environ.get(self._key_env, "") or (self._resolver() if self._resolver else "")
        if not key:
            raise ProviderError(f"API key missing: set {self._key_env}.", retryable=False)
        return {"Authorization": f"Bearer {key}"}

    def list_models(self) -> list[str]:
        return [m["id"] for m in self.transport.get_json(f"{self.base_url}/models", self._headers()).get("data", [])]

    @staticmethod
    def _convert(messages: list[Message], system: str) -> list:
        out: list = [{"role": "system", "content": system}] if system else []
        for m in messages:
            if m.role == "tool":
                out.append({"role": "tool", "tool_call_id": m.tool_call_id, "content": m.content})
            elif m.role == "assistant":
                item: dict = {"role": "assistant", "content": m.content or None}
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
                parts: list = [{"type": "text", "text": m.content}]
                parts += [
                    {"type": "image_url", "image_url": {"url": f"data:{i.media_type};base64,{i.data}"}}
                    for i in m.images
                ]
                out.append({"role": "user", "content": parts})
            else:
                out.append({"role": "user", "content": m.content})
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
        calls: dict[int, dict] = {}
        finish = "stop"
        for line in self.transport.stream_lines(f"{self.base_url}/chat/completions", self._headers(), body, cancel):
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if payload == "[DONE]":
                break
            try:
                ev = json.loads(payload)
            except ValueError:
                continue
            if ev.get("error"):
                raise ProviderError("OpenAI: " + str(ev["error"].get("message", ev["error"])))
            for ch in ev.get("choices", []):
                d = ch.get("delta", {})
                if d.get("content"):
                    yield StreamEvent("text", text=d["content"])
                for tc in d.get("tool_calls") or []:
                    slot = calls.setdefault(tc.get("index", 0), {"id": "", "name": "", "args": ""})
                    slot["id"] = tc.get("id") or slot["id"]
                    fn = tc.get("function", {})
                    slot["name"] = fn.get("name") or slot["name"]
                    slot["args"] += fn.get("arguments", "")
                finish = ch.get("finish_reason") or finish
        for i in sorted(calls):
            c = calls[i]
            try:
                args = json.loads(c["args"]) if c["args"] else {}
            except ValueError:
                args = {}
            yield StreamEvent("tool_call", tool_call=ToolCall(c["id"] or f"call-{i}", c["name"], args))
        yield StreamEvent("done", stop_reason="tool_use" if calls else finish)
