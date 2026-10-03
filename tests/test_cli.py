from __future__ import annotations

import json

from brok import cli
from brok.agent.tools import ApprovalRequest, Risk
from brok.config import BrokConfig
from brok.core import build_orchestrator, build_tools


def test_orchestrator_local_only_filters_cloud(monkeypatch):
    cfg = BrokConfig()
    cfg.ai.provider, cfg.ai.fallbacks, cfg.ai.local_only = "claude", ["ollama", "openai"], True
    assert [p.name for p in build_orchestrator(cfg).chain()] == ["ollama"]
    cfg.ai.local_only = False
    assert [p.name for p in build_orchestrator(cfg).chain()] == ["claude", "ollama", "openai"]


def test_local_only_offers_no_network_tools(tmp_path):
    cfg = BrokConfig()
    cfg.github.enabled, cfg.web.search_provider = True, "brave"
    assert "github_issues" in build_tools(cfg, str(tmp_path)).names()
    cfg.ai.local_only = True
    names = build_tools(cfg, str(tmp_path)).names()
    assert "github_issues" not in names and "web_search" not in names and "read_file" in names


def test_terminal_approver_denies_when_not_interactive(capsys, monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: False, raising=False)
    r = ApprovalRequest("delete_file", {"path": "a"}, Risk.HIGH, "delete a", diff=None)
    assert cli.terminal_approver(r) is False and "denied" in capsys.readouterr().out


def test_cli_health_and_memory(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("brok.paths.config_dir", lambda: tmp_path)
    (tmp_path / "a.py").write_text("# TODO: x\n")
    assert cli.main(["--project", str(tmp_path), "health"]) == 0
    assert "not a professional security audit" in capsys.readouterr().out
    assert cli.main(["memory", "add", "preference", "short answers"]) == 0
    assert cli.main(["memory", "add", "longterm", "key sk-ant-abcdefghijklmnop"]) == 1
    cli.main(["memory", "list"])
    out = capsys.readouterr().out
    assert "short answers" in out and "sk-ant" not in json.dumps(out)


def test_agent_end_to_end_with_scripted_provider(tmp_path, monkeypatch):
    from brok.ai.messages import StreamEvent, ToolCall
    from brok.ai.orchestrator import AIOrchestrator

    (tmp_path / "x.py").write_text("print(1)\n")
    turns = [
        [
            StreamEvent("tool_call", tool_call=ToolCall("1", "write_file", {"path": "x.py", "content": "print(2)\n"})),
            StreamEvent("done"),
        ],
        [StreamEvent("text", text="انجام شد"), StreamEvent("done")],
    ]

    class P:
        name, is_local, supports_tools = "s", True, True
        chat = lambda self, m, s="", t=None, c=None: iter(turns.pop(0))  # noqa: E731

    monkeypatch.setattr("brok.cli.build_orchestrator", lambda cfg, tr=None: AIOrchestrator({"s": P()}, "s"))
    monkeypatch.setattr("brok.paths.config_dir", lambda: tmp_path / "cfg")
    asked = []
    rc = cli._run_agent(
        BrokConfig(), "change", str(tmp_path), "CODING", approver=lambda r: asked.append(r.diff) or True
    )
    assert rc == 0 and (tmp_path / "x.py").read_text() == "print(2)\n" and "-print(1)" in asked[0]
    turns[:] = [
        [
            StreamEvent("tool_call", tool_call=ToolCall("1", "write_file", {"path": "x.py", "content": "print(3)\n"})),
            StreamEvent("done"),
        ],
        [StreamEvent("text", text="ok"), StreamEvent("done")],
    ]
    cli._run_agent(BrokConfig(), "change", str(tmp_path), "CODING", approver=lambda r: False)
    assert (tmp_path / "x.py").read_text() == "print(2)\n"  # rejected edit never applied
