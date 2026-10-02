from __future__ import annotations

import json

import pytest

from brok.ai.messages import ImageInput, Message, ToolCall, ToolSchema
from brok.ai.orchestrator import AIOrchestrator
from brok.ai.providers import ClaudeProvider, OllamaProvider, OpenAIProvider
from brok.ai.transport import ProviderError


class FakeTransport:
    def __init__(self, lines=None, json_data=None, fail=None):
        self.lines, self.json_data, self.fail = lines or [], json_data, fail
        self.last = None

    def stream_lines(self, url, headers, body, cancel=None):
        self.last = (url, headers, body)
        if self.fail:
            raise self.fail
        yield from self.lines

    def get_json(self, url, headers):
        self.last = (url, headers, None)
        return self.json_data


def sse(*events):
    return ["data: " + json.dumps(e) for e in events]


def test_claude_streams_text_and_tool_use(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-123456789")
    t = FakeTransport(sse(
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "سلام"}},
        {"type": "content_block_start", "index": 1, "content_block": {"type": "tool_use", "id": "tu1", "name": "read_file"}},
        {"type": "content_block_delta", "index": 1, "delta": {"type": "input_json_delta", "partial_json": '{"path":'}},
        {"type": "content_block_delta", "index": 1, "delta": {"type": "input_json_delta", "partial_json": '"a.py"}'}},
        {"type": "content_block_stop", "index": 1},
        {"type": "message_delta", "delta": {"stop_reason": "tool_use"}},
        {"type": "message_stop"},
    ))
    p = ClaudeProvider(transport=t)
    ev = list(p.chat([Message("user", "hi")], "sys", [ToolSchema("read_file", "d", {"type": "object"})]))
    assert ev[0].text == "سلام"
    assert ev[1].tool_call.arguments == {"path": "a.py"} and ev[1].tool_call.id == "tu1"
    assert ev[-1].kind == "done" and ev[-1].stop_reason == "tool_use"
    url, headers, body = t.last
    assert url.endswith("/v1/messages") and body["system"] == "sys" and body["tools"][0]["input_schema"]
    assert headers["x-api-key"].startswith("sk-ant")


def test_claude_requires_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(ProviderError):
        list(ClaudeProvider(transport=FakeTransport()).chat([Message("user", "x")]))


def test_claude_converts_tool_results_and_images(monkeypatch):
    msgs = [Message("user", "look", images=[ImageInput("QUJD")]),
            Message("assistant", "", [ToolCall("t1", "read_file", {"path": "x"})]),
            Message("tool", "content", tool_call_id="t1")]
    out = ClaudeProvider._convert(msgs)
    assert out[0]["content"][0]["type"] == "image"
    assert out[1]["content"][0]["type"] == "tool_use"
    assert out[2]["role"] == "user" and out[2]["content"][0]["type"] == "tool_result"


def test_ollama_stream_and_local_flag():
    t = FakeTransport([json.dumps({"message": {"content": "he"}}), json.dumps({"message": {"content": "llo",
        "tool_calls": [{"function": {"name": "git_status", "arguments": {}}}]}, "done": True})])
    p = OllamaProvider(transport=t)
    ev = list(p.chat([Message("user", "x")]))
    assert "".join(e.text for e in ev if e.kind == "text") == "hello"
    assert ev[-1].stop_reason == "tool_use" and p.is_local and p.badge == "LOCAL AI"
    assert not OllamaProvider(host="http://10.0.0.5:11434").is_local


def test_ollama_models():
    p = OllamaProvider(transport=FakeTransport(json_data={"models": [{"name": "a"}, {"name": "b"}]}))
    assert p.list_models() == ["a", "b"] and "OK" in p.test_connection()


def test_openai_tool_call_assembly(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-0123456789abcdef")
    t = FakeTransport(sse(
        {"choices": [{"delta": {"content": "x"}}]},
        {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "c1", "function": {"name": "list_directory", "arguments": '{"pa'}}]}}]},
        {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": 'th":"."}'}}]}, "finish_reason": "tool_calls"}]},
    ) + ["data: [DONE]"])
    ev = list(OpenAIProvider(transport=t).chat([Message("user", "x")]))
    assert ev[1].tool_call.arguments == {"path": "."} and ev[-1].stop_reason == "tool_use"


class Stub:
    def __init__(self, name, local, events=None, exc=None):
        self.name, self.is_local, self.supports_tools, self._ev, self._exc = name, local, True, events or [], exc

    def chat(self, messages, system="", tools=None, cancel=None):
        if self._exc:
            raise self._exc
        yield from self._ev


def test_orchestrator_falls_back_and_local_only():
    from brok.ai.messages import StreamEvent

    bad = Stub("claude", False, exc=ProviderError("down"))
    good = Stub("ollama", True, [StreamEvent("text", text="ok"), StreamEvent("done")])
    sent = []
    o = AIOrchestrator({"claude": bad, "ollama": good}, "claude", ["ollama"], on_send=lambda *a: sent.append(a))
    assert [e.text for e in o.stream([Message("user", "hi")]) if e.kind == "text"] == ["ok"]
    assert sent[0][0] == "claude" and sent[1][:2] == ("ollama", True)
    only = AIOrchestrator({"claude": bad, "ollama": good}, "claude", ["ollama"], local_only=True)
    assert [p.name for p in only.chain()] == ["ollama"]
    none = AIOrchestrator({"claude": bad}, "claude", local_only=True)
    with pytest.raises(ProviderError):
        list(none.stream([Message("user", "x")]))
