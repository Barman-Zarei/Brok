from __future__ import annotations

import json

import pytest

from brok import llm, llm_claude, llm_vendors


def test_claude_is_a_builtin_vendor_needing_a_key():
    v = llm_vendors.builtin_vendors()["claude"]
    assert v.kind == llm_vendors.KIND_CLAUDE and v.needs_key and v.api_key_env == "ANTHROPIC_API_KEY"
    with pytest.raises(llm.LLMDependencyError):
        llm.create_backend_for_vendor(v, 5)  # no key configured


def test_claude_backend_reply(monkeypatch):
    lines = ["data: " + json.dumps(e) for e in (
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "سلام "}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "دنیا"}},
        {"type": "message_stop"})]
    b = llm_claude.ClaudeBackend(base_url="", api_key="sk-ant-xxxxxxxxxxxx", model="m", timeout=5)
    b.provider.transport = type("T", (), {"stream_lines": lambda s, u, h, body, c=None: iter(lines)})()
    assert b.reply("hi", "sys") == "سلام دنیا"


def test_default_prompt_is_brok_not_cat():
    from pathlib import Path

    text = (Path(llm.__file__).parent / "PROMPT.j2").read_text(encoding="utf-8")
    assert "Brok" in text and "Persian" in text and "Meow" not in text and "swear" not in text
