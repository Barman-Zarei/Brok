# ruff: noqa: E501  (long literal SSE lines / command lists)
"""Regression tests for the debug pass (0.2.x): loop cancel/deadline per tool dispatch, sandbox, tools, providers."""

import os
import subprocess
import time

import pytest

from brok.agent.builtin_tools import build_registry
from brok.agent.loop import AgentLoop, Limits
from brok.agent.sandbox import BLOCKED, SAFE, classify_command, run_command
from brok.agent.tools import Confirm, PermissionPolicy, Risk, ToolRegistry, ToolSpec
from brok.ai.messages import INVALID_ARGS_KEY, Message, StreamEvent, ToolCall
from brok.ai.orchestrator import AIOrchestrator
from brok.ai.providers.base import AIProvider
from brok.ai.providers.claude import ClaudeProvider
from brok.ai.providers.ollama import OllamaProvider
from brok.ai.providers.openai_compat import OpenAIProvider
from brok.ai.transport import ProviderError, UrllibTransport


# ---------------------------------------------------------------- helpers
class FakeOrch:
    def __init__(self, turns, on_stream=None):
        self.turns, self.on_stream, self.calls = list(turns), on_stream, 0

    def stream(self, msgs, mode, schemas, language):
        self.calls += 1
        if self.on_stream:
            self.on_stream()
        yield from self.turns.pop(0)

    def cancel(self):
        pass


def tc(i, name="t"):
    return StreamEvent("tool_call", tool_call=ToolCall(str(i), name, {}))


def reg_with(func):
    r = ToolRegistry(PermissionPolicy())
    r.register(ToolSpec("t", "d", {"type": "object", "properties": {}}, Risk.LOW, Confirm.NEVER, func))
    return r


class FakeTransport:
    def __init__(self, lines):
        self.lines = lines

    def stream_lines(self, url, headers, body, cancel=None):
        yield from self.lines


def repo(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "a@b.c"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "n"], cwd=tmp_path, check=True)
    (tmp_path / "a.txt").write_text("committed\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=tmp_path, check=True)
    return tmp_path


# ================================================= 1. the claim: loop checks
def test_L1_cancel_between_tools_stops_dispatch():
    ran = []
    holder = {}

    def tool():
        ran.append(1)
        holder["loop"].cancel()
        return "ok"

    loop = AgentLoop(FakeOrch([[tc(1), tc(2), tc(3)]]), reg_with(tool))
    holder["loop"] = loop
    res = loop.run("x")
    assert len(ran) == 1, f"tools executed after cancel: {len(ran)} of 3"
    ids = {m.tool_call_id for m in res.messages if m.role == "tool"}
    assert ids == {"1", "2", "3"}, "every tool_call needs a tool result (even 'skipped') or history is invalid"


def test_L2_deadline_between_tools_stops_dispatch():
    now = [0.0]
    ran = []

    def tool():
        ran.append(1)
        now[0] += 1000  # tool is slow, blows the 600s deadline
        return "ok"

    loop = AgentLoop(FakeOrch([[tc(1), tc(2), tc(3)]]), reg_with(tool), clock=lambda: now[0])
    loop.run("x")
    assert len(ran) == 1, f"tools executed after deadline: {len(ran)} of 3"


def test_L3_deadline_crossed_during_model_turn_blocks_all_tools():
    now = [0.0]
    ran = []
    loop = AgentLoop(
        FakeOrch([[tc(1)]], on_stream=lambda: now.__setitem__(0, 9999)),
        reg_with(lambda: ran.append(1) or "ok"),
        clock=lambda: now[0],
    )
    res = loop.run("x")
    assert not ran, "tool ran although deadline had already passed (only `cancel` is re-checked after the stream)"
    assert res.status == "timeout"


def test_L4_cancel_before_run_is_not_lost():
    orch = FakeOrch([[StreamEvent("text", text="hi"), StreamEvent("done")]])
    loop = AgentLoop(orch, reg_with(lambda: "ok"))
    loop.cancel()
    res = loop.run("x")
    assert res.status == "cancelled" and orch.calls == 0  # run() does self._cancel.clear() first


def test_L5_total_runtime_bounded_by_timeout():
    # timeout_seconds=600 but 60 tools x 120s command timeout is allowed: nothing bounds a batch
    now = [0.0]
    loop = AgentLoop(
        FakeOrch([[tc(i) for i in range(60)]]),
        reg_with(lambda: now.__setitem__(0, now[0] + 120) or "ok"),
        limits=Limits(timeout_seconds=600),
        clock=lambda: now[0],
    )
    loop.run("x")
    assert now[0] <= 600 + 120, f"simulated runtime {now[0]}s vs 600s limit"


def test_L6_stop_reason_length_is_not_reported_as_done():
    loop = AgentLoop(
        FakeOrch([[StreamEvent("text", text="half an ans"), StreamEvent("done", stop_reason="max_tokens")]]),
        reg_with(lambda: "ok"),
    )
    assert loop.run("x").status != "done", "truncated model output is reported as success"


# ================================================= 2. provider / transport
class BoomProvider(AIProvider):
    name = "boom"

    def __init__(self, exc):
        super().__init__("m", transport=object())
        self.exc = exc

    def chat(self, messages, system="", tools=None, cancel=None):
        yield StreamEvent("text", text="partial")
        raise self.exc

    def list_models(self):
        return []


def test_P1_non_provider_error_does_not_crash_loop():
    orch = AIOrchestrator({"boom": BoomProvider(ConnectionResetError("reset"))}, "boom")
    res = AgentLoop(orch, reg_with(lambda: "ok")).run("x")  # raises today
    assert res.status == "error"


def test_P2_transport_wraps_mid_stream_errors(monkeypatch):
    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def __iter__(self):
            yield b"data: {}\n"
            raise ConnectionResetError("peer reset")

    t = UrllibTransport()
    monkeypatch.setattr(t, "_open", lambda *a, **k: Resp())
    with pytest.raises(ProviderError):
        list(t.stream_lines("http://x", {}, {}))


def test_P3_no_tool_capable_provider_gives_clear_message():
    class NoTools(BoomProvider):
        supports_tools = False

    orch = AIOrchestrator({"boom": NoTools(OSError())}, "boom")
    from brok.ai.messages import ToolSchema

    with pytest.raises(ProviderError) as e:
        list(orch.stream([Message("user", "hi")], "CHAT", [ToolSchema("t", "d", {})]))
    assert "None" not in str(e.value)


def test_P4_openai_string_error_event_is_provider_error():
    p = OpenAIProvider(key_resolver=lambda: "k", transport=FakeTransport(['data: {"error": "rate limited"}']))
    with pytest.raises(ProviderError):
        list(p.chat([Message("user", "hi")]))  # AttributeError today


@pytest.mark.parametrize("kind", ["openai", "claude"])
def test_P5_truncated_tool_args_are_not_executed_as_empty_call(kind):
    if kind == "openai":
        lines = [
            'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"c1","function":{"name":"git_stash","arguments":"{\\"action\\": \\"po"}}]}}]}',
            "data: [DONE]",
        ]
        p = OpenAIProvider(key_resolver=lambda: "k", transport=FakeTransport(lines))
    else:
        lines = [
            'data: {"type":"content_block_start","index":0,"content_block":{"type":"tool_use","id":"c1","name":"git_stash"}}',
            'data: {"type":"content_block_delta","index":0,"delta":{"type":"input_json_delta","partial_json":"{\\"action\\": \\"po"}}',
            'data: {"type":"content_block_stop","index":0}',
            'data: {"type":"message_delta","delta":{"stop_reason":"max_tokens"}}',
            'data: {"type":"message_stop"}',
        ]
        p = ClaudeProvider(key_resolver=lambda: "k", transport=FakeTransport(lines))
    calls = [e.tool_call for e in p.chat([Message("user", "hi")]) if e.kind == "tool_call"]
    assert not any(c.arguments == {} for c in calls), "garbled args silently become {} -> git_stash defaults to 'push'"


def test_P6_tool_call_ids_unique_across_turns():
    line = '{"message":{"tool_calls":[{"function":{"name":"x","arguments":{}}}]},"done":true}'
    p = OllamaProvider(transport=FakeTransport([line]))
    a = [e.tool_call.id for e in p.chat([Message("user", "1")]) if e.kind == "tool_call"]
    b = [e.tool_call.id for e in p.chat([Message("user", "2")]) if e.kind == "tool_call"]
    assert a != b, f"both turns use id {a}"


def test_P7_claude_no_empty_text_block_for_image_only_message():
    from brok.ai.messages import ImageInput

    out = ClaudeProvider._convert([Message("user", "", images=[ImageInput("AAAA")])])
    texts = [b for b in out[0]["content"] if b["type"] == "text"]
    assert all(b["text"] for b in texts), "empty text block (Anthropic API rejects these)"


# ================================================= 3. sandbox / permission gate
@pytest.mark.parametrize(
    "cmd",
    [
        "git diff --output=/tmp/pwn.txt",
        "git log --output=/tmp/pwn.txt",
        "cat .env",
        "git branch -D main",
        "git remote add x http://e",
    ],
)
def test_S1_read_only_whitelist_must_not_write_or_read_secrets(cmd):
    assert classify_command(cmd).level != SAFE, f"{cmd!r} runs with NO approval"


@pytest.mark.parametrize("cmd", ["rm -rf ~/", "rm -rf /*", "rm -rf $HOME/", "rm --recursive --force /"])
def test_S2_destructive_rm_variants_are_blocked(cmd):
    assert classify_command(cmd).level == BLOCKED


def test_S3_windows_quote_handling():
    r = run_command('python3 -c "print(7)"', os.getcwd(), os_name="Windows")
    assert r.output.strip() == "7", f"posix=False keeps literal quotes: got {r.output!r}"


def test_S4_timeout_is_honoured_with_grandchild():
    t0 = time.time()
    run_command("sh -c 'sleep 4 & sleep 4'", os.getcwd(), timeout=1)
    assert time.time() - t0 < 3, f"took {time.time() - t0:.1f}s for a 1s timeout"


def test_S5_timeout_keeps_partial_output():
    r = run_command("python3 -u -c \"print('partial');import time;time.sleep(4)\"", os.getcwd(), timeout=1)
    assert "partial" in r.output


# ================================================= 4. builtin tools
def test_T1_cannot_plant_code_execution_via_dot_git(tmp_path):
    root = repo(tmp_path)
    marker = tmp_path.parent / "pwned_marker"
    marker.unlink(missing_ok=True)
    reg = build_registry(str(root), PermissionPolicy(auto_approve_medium=True))
    cfg = (root / ".git" / "config").read_text() + f"\n[core]\n\tfsmonitor = touch {marker}; echo\n"
    reg.execute("write_file", {"path": ".git/config", "content": cfg})
    reg.execute("git_status", {})  # LOW risk, never asks
    assert not marker.exists(), "write_file into .git/config -> arbitrary command on next git_status"


def test_T2_move_file_cannot_bypass_secret_guard(tmp_path):
    (tmp_path / ".env").write_text("KEY=supersecret\n")
    reg = build_registry(str(tmp_path), PermissionPolicy(auto_approve_medium=True))
    reg.execute("move_file", {"src": ".env", "dst": "notes.txt"})
    assert "supersecret" not in reg.execute("read_file", {"path": "notes.txt"})


def test_T3_move_file_refuses_dot_git(tmp_path):
    repo(tmp_path)
    reg = build_registry(str(tmp_path), PermissionPolicy(auto_approve_medium=True))
    reg.execute("move_file", {"src": ".git", "dst": "gone"})
    assert (tmp_path / ".git").exists()


def test_T4_git_checkout_does_not_discard_file_changes(tmp_path):
    repo(tmp_path)
    (tmp_path / "a.txt").write_text("my unsaved work\n")
    reg = build_registry(str(tmp_path), PermissionPolicy(auto_approve_medium=True))
    reg.execute("git_checkout", {"branch": "a.txt"})  # a *file* name passes the ref regex
    assert (tmp_path / "a.txt").read_text() == "my unsaved work\n"


def test_T5_search_text_survives_outside_symlink(tmp_path):
    (tmp_path / "x.py").write_text("needle\n")
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("zzz")
    (tmp_path / "link.txt").symlink_to(outside)
    reg = build_registry(str(tmp_path), PermissionPolicy())
    assert "needle" in reg.execute("search_text", {"pattern": "needle"})


def test_T6_search_text_on_single_file(tmp_path):
    (tmp_path / "x.py").write_text("needle\n")
    reg = build_registry(str(tmp_path), PermissionPolicy())
    assert "needle" in reg.execute("search_text", {"pattern": "needle", "path": "x.py"})


def test_T7_read_file_line_numbers_match_search_text(tmp_path):
    (tmp_path / "x.py").write_text("a\x0cb\nneedle\n")  # form feed: str.splitlines() splits on it
    reg = build_registry(str(tmp_path), PermissionPolicy())
    s = reg.execute("search_text", {"pattern": "needle"})  # x.py:2
    r = reg.execute("read_file", {"path": "x.py"})
    assert "3: needle" not in r, f"search says line 2, read_file says line 3\n{s}\n{r}"


def test_T8_write_file_preserves_crlf(tmp_path):
    p = tmp_path / "w.txt"
    p.write_bytes(b"a\r\nb\r\n")
    reg = build_registry(str(tmp_path), PermissionPolicy(auto_approve_medium=True))
    reg.execute("write_file", {"path": "w.txt", "content": "a\nb\nc\n"})
    assert b"\r\n" in p.read_bytes()


def test_T9_delete_symlink_deletes_link_not_target(tmp_path):
    (tmp_path / "real.txt").write_text("data")
    (tmp_path / "ln.txt").symlink_to(tmp_path / "real.txt")
    reg = build_registry(str(tmp_path), PermissionPolicy())
    reg.policy.approver = lambda req: True
    reg.execute("delete_file", {"path": "ln.txt"})
    assert (tmp_path / "real.txt").exists()


def test_T10_internal_typeerror_not_reported_as_bad_arguments():
    def buggy():
        return 1 + "a"  # internal bug, arguments are fine

    out = reg_with(buggy).execute("t", {})
    assert "bad arguments" not in out


# ================================================= 5. misc
def test_M1_health_has_no_filename_exemption(tmp_path):
    from brok.agent.health import analyze

    (tmp_path / "test_agent.py").write_text('API_KEY = "sk-ant-abcdefghijklmnop"\n')
    cats = [(f.category, f.where) for f in analyze(str(tmp_path)).findings]
    assert ("security", "test_agent.py") in cats


def test_M2_infer_mode_persian_error_word():
    from brok.ai.orchestrator import infer_mode

    assert infer_mode("این خطا رو درست کن") == infer_mode("این ارور رو درست کن")


def test_M3_traceback_parser_exception_group():
    from brok.agent.debugger import parse_traceback

    assert parse_traceback("Traceback...\nExceptionGroup: boom (2 sub-exceptions)").error_type


# ================================================= 6. new behaviour introduced by the fixes
def test_E1_effects_are_recorded_before_and_after_each_dispatch():
    seen = []
    loop = AgentLoop(
        FakeOrch([[tc(1), tc(2)], [StreamEvent("text", text="ok"), StreamEvent("done")]]),
        reg_with(lambda: "fine"),
        on_effect=lambda e: seen.append((e["call_id"], e["state"])),
    )
    res = loop.run("x")
    assert seen == [("1", "started"), ("1", "finished"), ("2", "started"), ("2", "finished")]
    assert [e["state"] for e in res.effects] == ["finished", "finished"] and res.effects[0]["outcome"] == "fine"


def test_E2_skipped_calls_are_recorded_as_skipped():
    holder = {}

    def tool():
        holder["loop"].cancel()
        return "ok"

    loop = AgentLoop(FakeOrch([[tc(1), tc(2)]]), reg_with(tool))
    holder["loop"] = loop
    res = loop.run("x")
    assert res.status == "cancelled" and [e["state"] for e in res.effects] == ["finished", "skipped"]
    assert res.messages[-1].content.startswith("SKIPPED")


def test_E3_truncated_turn_runs_no_tools():
    ran = []
    turn = [tc(1), StreamEvent("done", stop_reason="max_tokens")]
    res = AgentLoop(FakeOrch([turn]), reg_with(lambda: ran.append(1) or "ok")).run("x")
    assert res.status == "truncated" and not ran


def test_E4_duplicate_tool_call_ids_are_made_unique():
    turns = [[tc(1)], [tc(1)], [StreamEvent("text", text="end"), StreamEvent("done")]]
    res = AgentLoop(FakeOrch(turns), reg_with(lambda: "ok")).run("x")
    ids = [c.id for m in res.messages for c in m.tool_calls]
    assert len(ids) == len(set(ids)) == 2
    assert {m.tool_call_id for m in res.messages if m.role == "tool"} == set(ids)


def test_E5_invalid_json_arguments_never_run_the_tool():
    ran = []
    out = reg_with(lambda: ran.append(1) or "ok").execute("t", {INVALID_ARGS_KEY: '{"a": "po'})
    assert not ran and out.startswith("ERROR") and "NOT run" in out


def test_E6_fsmonitor_planted_outside_the_tools_does_not_run(tmp_path):
    root = repo(tmp_path)
    marker = tmp_path.parent / "fsmonitor_marker"
    marker.unlink(missing_ok=True)
    subprocess.run(["git", "config", "core.fsmonitor", f"touch {marker}; echo"], cwd=root, check=True)
    build_registry(str(root), PermissionPolicy()).execute("git_status", {})
    assert not marker.exists()


def test_E7_git_stash_rejects_unknown_action(tmp_path):
    repo(tmp_path)
    out = build_registry(str(tmp_path), PermissionPolicy(auto_approve_medium=True)).execute(
        "git_stash", {"action": "pp"}
    )
    assert out.startswith("ERROR")


def test_E8_terminal_panel_command_can_be_approved_without_agent(tmp_path):
    pytest.importorskip("PySide6")
    from PySide6 import QtWidgets

    from brok.ai.orchestrator import AIOrchestrator as Orch
    from brok.workspace_ui import WorkspaceWindow

    QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    asked = []
    w = WorkspaceWindow(
        str(tmp_path),
        Orch({}, "none"),
        lambda root, approver: build_registry(root, PermissionPolicy(approver=approver)),
        Limits(),
    )
    w._show_approval = lambda req: asked.append(req) or True
    w.cmd_input.setText("python3 -c pass")  # unlisted program: needs approval
    w.run_terminal_command()
    assert asked and "exit=0" in w.output.toPlainText()


# ================================================= 7. second round: Stop reaches blocking work
def test_K1_run_command_is_killed_by_cancel():
    import threading

    ev = threading.Event()
    threading.Timer(0.5, ev.set).start()
    t0 = time.time()
    r = run_command("sleep 8", os.getcwd(), timeout=30, cancel=ev)
    assert r.cancelled and time.time() - t0 < 4


def test_K2_stop_kills_a_running_tool_and_skips_the_rest(tmp_path):
    import threading

    reg = build_registry(str(tmp_path), PermissionPolicy(approver=lambda req: True))
    call = lambda i: StreamEvent("tool_call", tool_call=ToolCall(str(i), "run_command", {"command": "sleep 8"}))  # noqa: E731
    loop = AgentLoop(FakeOrch([[call(1), call(2)]]), reg)
    threading.Timer(0.6, loop.cancel).start()
    t0 = time.time()
    res = loop.run("x")
    assert res.status == "cancelled" and time.time() - t0 < 5
    assert [e["state"] for e in res.effects] == ["finished", "skipped"]


def test_K3_cancel_unblocks_a_silent_server():
    import http.server
    import threading

    class H(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            self.wfile.write(b"data: first\n\n")
            self.wfile.flush()
            time.sleep(8)  # then total silence

        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    cancel = threading.Event()
    threading.Timer(0.6, cancel.set).start()
    t0 = time.time()
    try:
        got = list(UrllibTransport().stream_lines(f"http://127.0.0.1:{srv.server_port}/", {}, {}, cancel=cancel))
    finally:
        srv.shutdown()
    assert got == ["data: first"] and time.time() - t0 < 4


@pytest.mark.parametrize("kind", ["openai", "claude", "ollama"])
def test_K4_stream_without_terminal_marker_is_an_error(kind):
    if kind == "openai":
        p = OpenAIProvider(
            key_resolver=lambda: "k", transport=FakeTransport(['data: {"choices":[{"delta":{"content":"hi"}}]}'])
        )
    elif kind == "claude":
        p = ClaudeProvider(
            key_resolver=lambda: "k",
            transport=FakeTransport(
                ['data: {"type":"content_block_start","index":0,"content_block":{"type":"text","text":""}}']
            ),
        )
    else:
        p = OllamaProvider(transport=FakeTransport(['{"message":{"content":"hi"},"done":false}']))
    with pytest.raises(ProviderError):
        list(p.chat([Message("user", "hi")]))


def test_K5_complete_streams_still_work():
    p = OpenAIProvider(
        key_resolver=lambda: "k",
        transport=FakeTransport(['data: {"choices":[{"delta":{"content":"hi"}}]}', "data: [DONE]"]),
    )
    assert [e.text for e in p.chat([Message("user", "hi")]) if e.kind == "text"] == ["hi"]


def test_K6_catastrophic_regex_is_rejected_not_run(tmp_path):
    (tmp_path / "x.py").write_text("a" * 40 + "!\n")
    reg = build_registry(str(tmp_path), PermissionPolicy())
    t0 = time.time()
    assert reg.execute("search_text", {"pattern": "(a+)+$"}).startswith("ERROR")
    assert time.time() - t0 < 2
    assert "x.py" in reg.execute("search_text", {"pattern": r"(a+)!"})  # ordinary groups still fine


def test_K7_list_directory_shows_build_dirs(tmp_path):
    (tmp_path / "build").mkdir()
    (tmp_path / "node_modules").mkdir()
    out = build_registry(str(tmp_path), PermissionPolicy()).execute("list_directory", {"path": "."})
    assert "build" in out and "node_modules" not in out
