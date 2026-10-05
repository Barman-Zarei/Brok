from __future__ import annotations

import pytest

from brok.agent.debugger import debug_prompt, parse_traceback
from brok.agent.health import analyze
from brok.agent.learning import learning_prompt
from brok.commands import parse_command
from brok.config import BrokConfig
from brok.memory import MemoryStore, SensitiveContentError

TB = """Traceback (most recent call last):
  File "app/main.py", line 3, in run
    total(None)
  File "app/util.py", line 2, in total
    return sum(items)
TypeError: 'NoneType' object is not iterable
"""


def test_memory_crud_and_privacy(tmp_path):
    m = MemoryStore(tmp_path / "m.json")
    a = m.add("preference", "پاسخ‌ها کوتاه باشند")
    m.add("project", "uses pytest", scope="/p")
    assert m.counts()["preference"] == 1 and "کوتاه" in m.context_for("/p") and "pytest" in m.context_for("/p")
    assert "pytest" not in m.context_for("/other")
    m.edit(a.id, "short answers")
    assert MemoryStore(tmp_path / "m.json").list("preference")[0].text == "short answers"  # persisted
    with pytest.raises(SensitiveContentError):
        m.add("longterm", "my key is sk-ant-abcdefghijklmnop")
    assert m.delete(a.id) and not m.delete(a.id)
    assert m.clear() == 1 and m.counts()["project"] == 0
    assert oct((tmp_path / "m.json").stat().st_mode)[-3:] == "600"


def test_config_defaults_env_and_no_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("BROK_PROFILE", "standard")  # this test is about the standard defaults, not a branch profile
    c = BrokConfig.load(tmp_path / "x.json", env={"BROK_AI_PROVIDER": "claude", "BROK_LOCAL_ONLY": "true"})
    assert c.ai.provider == "claude" and c.ai.local_only and c.ui.language == "fa" and c.security.diff_first
    p = c.save(tmp_path / "x.json")
    text = p.read_text()
    assert "api_key" not in text.lower() and BrokConfig.load(p, env={}).ai.provider == "claude"


def test_commands():
    assert parse_command("/fix این ارور").mode == "DEBUG" and parse_command("/fix x").args == "x"
    assert parse_command("/search python 3.13").name == "search"
    assert parse_command("بروک این ارور یعنی چی؟").mode == "DEBUG"
    assert parse_command("hello there").mode == "CHAT" and parse_command("  ") is None


def test_debugger(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "util.py").write_text("def total(items):\n    return sum(items)\n")
    e = parse_traceback(TB)
    assert e.error_type == "TypeError" and e.frames[-1].func == "total" and e.frames[-1].line == 2
    p = debug_prompt(TB, str(tmp_path))
    assert ">> 2:     return sum(items)" in p and "Persian" in p


def test_learning_prompts():
    assert "Do NOT include the solution" in learning_prompt("exercise", "for loop")
    with pytest.raises(ValueError):
        learning_prompt("nope", "x")


def test_health_report(tmp_path):
    (tmp_path / "a.py").write_text(
        "# TODO: fix\ntry:\n    pass\nexcept:\n    pass\nkey='sk-ant-abcdefghijklmnop'\neval('1')\n"
    )
    r = analyze(str(tmp_path))
    cats = {f.category for f in r.findings}
    assert {"todo", "quality", "security", "tests"} <= cats and "not a professional" in r.disclaimer
