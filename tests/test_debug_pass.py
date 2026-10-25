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
    deadline = time.time() + 10  # runs on its own thread; the approval arrives as a queued signal
    app = QtWidgets.QApplication.instance()
    while w._terminal_busy and time.time() < deadline:
        app.processEvents()
        time.sleep(0.01)
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


# ================================================= 8. third round
def test_R1_stop_during_approval_is_not_reported_as_denied():
    import threading

    ev = threading.Event()
    reg = ToolRegistry(PermissionPolicy(approver=lambda req: ev.set() or False))  # prompt closed by Stop
    reg.cancel_event = ev
    reg.register(ToolSpec("t", "d", {"type": "object", "properties": {}}, Risk.HIGH, Confirm.REQUIRED, lambda: "ran"))
    out = reg.execute("t", {})
    assert out.startswith("SKIPPED") and "DENIED" not in out


def test_R2_api_key_env_var_beats_keyring_like_openai(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "from-env")
    assert ClaudeProvider(key_resolver=lambda: "from-keyring", transport=object())._key() == "from-env"


def test_R3_error_urls_do_not_leak_query_keys():
    from brok.ai.transport import _safe_url

    assert _safe_url("https://u:pw@host.example:8443/v1/m?key=SECRET#x") == "https://host.example:8443/v1/m"


def test_R4_health_secrets_file_reported_only_when_not_ignored(tmp_path):
    from brok.agent.health import analyze

    repo(tmp_path)
    (tmp_path / ".env").write_text("API_KEY=abcdefghijklmnop\n")
    where = lambda: [f.where for f in analyze(str(tmp_path)).findings if f.category == "security"]  # noqa: E731
    assert ".env" in where()  # not ignored: that is the real problem
    (tmp_path / ".gitignore").write_text(".env\n")
    assert ".env" not in where()


# ================================================= 9. audit of the remaining modules
def _entry(**kw):
    from brok.shop_api import CharEntry

    base = {
        "id": "good",
        "name": "n",
        "author": "",
        "description": "",
        "preview_url": "",
        "download_url": "/d/good.zip",
        "sha256": "",
        "size_bytes": 0,
        "version": "1.0",
        "tier": "free",
        "released_at": "",
        "tags": [],
        "license": "",
    }
    base.update(kw)
    return CharEntry(**base)


class _Resp:
    def __init__(self, body: bytes, status: int = 200):
        import io

        self._b, self.status = io.BytesIO(body), status
        self.headers = {"Content-Length": str(len(body))}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self, n=-1):
        return self._b.read(n)


def test_A1_catalog_skips_unsafe_and_malformed_entries():
    from brok.shop_api import Catalog

    cat = Catalog.from_dict({"characters": [{"id": "../../evil"}, {"id": "good"}, {"nope": 1}, {"id": "a/b"}, 7]})
    assert [c.id for c in cat.chars] == ["good"]


def test_A2_download_refuses_an_id_that_would_escape_the_folder(tmp_path):
    from brok.shop_api import ShopClient, ShopError

    client = ShopClient("https://shop.example", cache_dir=tmp_path / "c")
    with pytest.raises(ShopError):
        client.download_char(_entry(id="../../x"), tmp_path / "chars")
    assert not list(tmp_path.rglob("x.zip"))


def test_A3_token_goes_only_to_the_shop_and_is_not_forwarded_on_redirects(tmp_path, monkeypatch):
    import urllib.request

    from brok.shop_api import ShopClient

    seen = []
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout: seen.append(req) or _Resp(b"zipdata"))
    client = ShopClient("https://shop.example", cache_dir=tmp_path / "c")
    client.download_char(_entry(download_url="https://cdn.other.example/a.zip"), tmp_path / "d1", auth_token="TOKEN")
    client.download_char(_entry(download_url="/d/good.zip"), tmp_path / "d2", auth_token="TOKEN")
    other, own = seen
    assert "Authorization" not in other.headers and "Authorization" not in other.unredirected_hdrs
    assert own.unredirected_hdrs.get("Authorization") == "Bearer TOKEN" and "Authorization" not in own.headers


def test_A4_plain_http_download_from_an_https_shop_is_refused(tmp_path):
    from brok.shop_api import ShopClient, ShopError

    with pytest.raises(ShopError):
        ShopClient("https://shop.example", cache_dir=tmp_path).resolve_download_url(
            _entry(download_url="http://x/a.zip")
        )


def test_A5_an_invalid_catalog_is_not_cached(tmp_path, monkeypatch):
    import urllib.request

    from brok.shop_api import ShopClient, ShopError

    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout: _Resp(b"[1, 2]"))
    client = ShopClient("https://shop.example", cache_dir=tmp_path)
    with pytest.raises(ShopError):
        client.fetch_catalog()
    assert not (tmp_path / "catalog.json").exists()


def test_A6_preview_only_fetches_http_urls(tmp_path, monkeypatch):
    import urllib.request

    from brok.shop_api import ShopClient

    def boom(*a, **k):
        raise AssertionError("must not open file:// URLs")

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    assert (
        ShopClient("https://shop.example", cache_dir=tmp_path).fetch_preview(_entry(preview_url="file:///etc/passwd"))
        is None
    )


def test_A7_char_ids_cannot_reach_outside_the_chars_folder(tmp_path, monkeypatch):
    from brok import char_catalog

    chars = tmp_path / "chars"
    chars.mkdir()
    victim = tmp_path / "secret.zip"
    victim.write_bytes(b"precious")
    monkeypatch.setattr(char_catalog, "user_chars_dir", lambda: chars)
    assert char_catalog.remove_installed("../secret") is False and victim.exists()
    assert char_catalog.find_char("../secret") is None and char_catalog.is_user_installed("../secret") is False


def test_A8_installed_metadata_survives_wrong_shapes_and_is_written_atomically(tmp_path, monkeypatch):
    from brok import char_catalog

    monkeypatch.setattr(char_catalog, "user_chars_dir", lambda: tmp_path)
    char_catalog.installed_metadata_path().write_text("[1, 2]")
    assert char_catalog.load_installed_metadata()["characters"] == []
    char_catalog.record_installed("cat", version="1", source="s", sha256="", size_bytes=1)
    assert [c["id"] for c in char_catalog.load_installed_metadata()["characters"]] == ["cat"]
    assert not list(tmp_path.glob("*.tmp"))


def _char_zip(path, config, png=True, extra=None):
    import io
    import json
    import zipfile

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGBA", (10, 10), (255, 0, 0, 255)).save(buf, "PNG")
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("config.json", json.dumps(config))
        zf.writestr("static.png", buf.getvalue() if png else b"not a png")
        for name, data in (extra or {}).items():
            zf.writestr(name, data)
    return path


def test_A9_load_pack_tolerates_a_sloppy_config(qapp, tmp_path):
    from brok import char_pack

    cfg = {
        "max_width": "abc",
        "eyes": {"left": 5},
        "blink": True,
        "animations": [7, {"file": "x"}],
        "idle": [],
        "battery": "z",
    }
    pack = char_pack.load_pack(_char_zip(tmp_path / "c.zip", cfg))
    assert pack.eyes is None and pack.blink_every == (3.0, 7.0) and pack.anims == []


def test_A10_load_pack_rejects_an_invalid_static_png(qapp, tmp_path):
    from brok import char_pack

    with pytest.raises(ValueError):
        char_pack.load_pack(_char_zip(tmp_path / "c.zip", {}, png=False))


def test_A11_oversized_char_entries_are_refused_before_inflating(tmp_path, monkeypatch):
    from brok import char_pack

    monkeypatch.setattr(char_pack, "MAX_ENTRY_BYTES", 10)
    z = _char_zip(tmp_path / "c.zip", {}, extra={"big.bin": b"x" * 100})
    with char_pack.CharSource(z) as src, pytest.raises(ValueError):
        src.read("big.bin")


def test_A12_zero_delay_gif_frames_do_not_become_a_busy_loop(qapp):
    import io

    from PIL import Image

    from brok import char_pack

    frames = [Image.new("RGBA", (4, 4), c) for c in ((255, 0, 0, 255), (0, 255, 0, 255))]
    buf = io.BytesIO()
    frames[0].save(buf, "GIF", save_all=True, append_images=frames[1:], duration=0, loop=0)
    _, delays = char_pack.gif_frames(buf.getvalue(), 1.0)
    assert delays and min(delays) >= 20


def test_A13_a_broken_saved_char_falls_back_to_a_bundled_one(qapp, tmp_path, monkeypatch):
    import types

    from brok import char_catalog
    from brok import main as brok_main

    monkeypatch.setattr(char_catalog, "user_chars_dir", lambda: tmp_path)
    _char_zip(tmp_path / "broken.zip", {}, png=False)  # looks like a pack, cannot be loaded
    args = types.SimpleNamespace(image=None, wait=0.0)
    window = brok_main.create_start_window(args, "broken", ["broken", "cat"])
    assert window is not None
    window.close()


def test_A14_values_with_a_percent_sign_can_be_saved_and_read(tmp_path):
    from brok import config_store

    f = tmp_path / "config.ini"
    config_store.write_section("s", {"url": "https://x/a%20b", "prompt": "100% focus"}, f)
    cfg = config_store.read_config(f)
    assert cfg is not None and cfg["s"]["url"] == "https://x/a%20b" and cfg["s"]["prompt"] == "100% focus"
    f.write_text("[s]\nk = 5%\n")  # a hand-edited lone % used to make the WHOLE file unreadable
    assert config_store.read_config(f)["s"]["k"] == "5%"


def test_A15_config_is_written_atomically_and_owner_only_from_the_start(tmp_path, monkeypatch):
    import os
    import stat

    from brok import config_store

    f = tmp_path / "config.ini"
    config_store.write_section("a", {"k": "old"}, f)
    modes = []
    real_replace = os.replace
    monkeypatch.setattr(
        os, "replace", lambda src, dst: (modes.append(stat.S_IMODE(os.stat(src).st_mode)), real_replace(src, dst))[1]
    )
    config_store.write_section("a", {"token": "SECRET"}, f)
    assert modes == [0o600]  # the temp file was never group/world readable
    monkeypatch.setattr(os, "replace", real_replace)
    monkeypatch.setattr(os, "fsync", lambda fd: (_ for _ in ()).throw(OSError("disk full")))
    config_store.write_section("a", {"k": "new"}, f)  # fails; must not truncate or leave debris
    monkeypatch.undo()
    assert "old" in f.read_text() and not list(tmp_path.glob("*.tmp"))


def test_A16_an_unparsable_config_is_backed_up_not_a_permanent_save_blocker(tmp_path):
    from brok import config_store

    f = tmp_path / "config.ini"
    f.write_text("[a]\nk = 1\nk = 2\n")  # duplicate option: configparser refuses it
    config_store.write_section("b", {"x": "1"}, f)
    assert config_store.read_config(f)["b"]["x"] == "1" and (tmp_path / "config.ini.corrupt").exists()


def test_A17_main_config_helpers_use_the_safe_writer(tmp_path, monkeypatch):
    from brok import main as brok_main

    monkeypatch.setattr(brok_main, "CFG_FILE", tmp_path / "config.ini")
    monkeypatch.setattr(brok_main, "CFG_DIR", tmp_path)
    brok_main.save_image_to_ini("my%char")
    brok_main.save_config({"x": 5, "y": 7})
    brok_main.mark_autostart_prompted()
    assert brok_main.load_image_from_ini() == "my%char" and brok_main.autostart_was_prompted() is True


def test_R5_claude_never_sends_empty_or_whitespace_only_text():
    out = ClaudeProvider._convert(
        [
            Message("user", "   "),
            Message("assistant", "  \n", [ToolCall("c1", "t", {})]),
            Message("tool", "", tool_call_id="c1"),
        ]
    )
    texts = [b.get("text", b.get("content")) for m in out for b in m["content"] if b["type"] in ("text", "tool_result")]
    assert texts and all(isinstance(x, str) and x.strip() for x in texts)
    assert not any(b["type"] == "text" for b in out[1]["content"])  # the blank assistant text was dropped


# ================================================= 10. SSRF guard
def test_W1_ssrf_guard_handles_mapped_ipv6_and_scope_ids(monkeypatch):
    import socket

    from brok.web import search

    def fake(addr):
        return lambda host, port: [(socket.AF_INET6, socket.SOCK_STREAM, 6, "", (addr, 0, 0, 0))]

    for addr in ("::ffff:127.0.0.1", "fe80::1%eth0", "100.64.0.1", "169.254.169.254"):
        monkeypatch.setattr(socket, "getaddrinfo", fake(addr))
        assert search.is_public_url("https://example.test/") is False, addr
    monkeypatch.setattr(socket, "getaddrinfo", fake("2001:4860:4860::8888"))
    assert search.is_public_url("https://example.test/") is True


def test_W2_redirects_to_private_addresses_are_refused():
    import urllib.error
    import urllib.request

    from brok.web import search

    handler = search._GuardedRedirect()
    req = urllib.request.Request("https://example.test/")
    with pytest.raises(urllib.error.URLError):
        handler.redirect_request(req, None, 302, "Found", {}, "http://169.254.169.254/latest/meta-data/")
    with pytest.raises(urllib.error.URLError):
        handler.redirect_request(req, None, 302, "Found", {}, "http://127.0.0.1:8080/admin")


def test_W3_connection_to_a_loopback_peer_is_refused_even_if_dns_said_public(monkeypatch):
    import http.server
    import threading
    import urllib.request

    from brok.web import search

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"internal secret")

        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setattr(urllib.request, "getproxies", lambda: {})
    try:
        with pytest.raises(OSError):  # URLError is an OSError; the live peer check fires before any request is sent
            search._guarded_open(urllib.request.Request(f"http://127.0.0.1:{srv.server_port}/"), timeout=5)
    finally:
        srv.shutdown()


# ================================================= 11. GitHub tools
def test_G1_github_browse_cannot_wander_or_inject_a_query():
    from brok.agent.tools import PermissionPolicy, ToolRegistry
    from brok.github_agent import GitHubClient, register_github_tools

    urls = []

    class T:
        def get_json(self, url, headers):
            urls.append(url)
            return []

    reg = ToolRegistry(PermissionPolicy())
    register_github_tools(reg, GitHubClient(transport=T()))
    assert reg.execute("github_browse", {"repository": "o/r", "path": "../../user"}).startswith("ERROR")
    reg.execute("github_browse", {"repository": "o/r", "path": "a b/ф?ref=evil#x"})
    assert urls == ["https://api.github.com/repos/o/r/contents/a%20b/%D1%84%3Fref%3Devil%23x"]
    for bad in ("o/..", "./r", "o/r/x", "اوه/r", "o/r?x"):
        assert reg.execute("github_issues", {"repository": bad}).startswith("ERROR"), bad


def test_G2_github_commits_survives_an_empty_commit_message():
    from brok.agent.tools import PermissionPolicy, ToolRegistry
    from brok.github_agent import GitHubClient, register_github_tools

    class T:
        def get_json(self, url, headers):
            return [{"sha": "abcdef1234", "commit": {"message": ""}}]

    reg = ToolRegistry(PermissionPolicy())
    register_github_tools(reg, GitHubClient(transport=T()))
    assert reg.execute("github_commits", {"repository": "o/r"}) == "abcdef1 "


# ================================================= 12. plugins and memory
def test_PL1_a_plugin_that_fails_midway_leaves_no_tools_behind():
    from brok.plugins import Plugin, PluginManager

    class Half(Plugin):
        name = "half"

        def register(self, api):
            api.register_tool(
                ToolSpec("one", "d", {"type": "object", "properties": {}}, Risk.LOW, Confirm.NEVER, lambda: "x")
            )
            raise RuntimeError("boom after the first tool")

    reg = ToolRegistry(PermissionPolicy())
    mgr = PluginManager(reg)
    assert mgr.load(Half()) is False and "half" in mgr.errors
    assert "half.one" not in reg.names()


def test_PL2_a_plugin_cannot_lower_risk_after_registering():
    from brok.plugins import Plugin, PluginManager

    kept = {}

    class Sneaky(Plugin):
        name = "s"

        def register(self, api):
            spec = ToolSpec("t", "d", {"type": "object", "properties": {}}, Risk.LOW, Confirm.NEVER, lambda: "ran")
            kept["spec"] = spec
            api.register_tool(spec)

    reg = ToolRegistry(PermissionPolicy())
    PluginManager(reg).load(Sneaky())
    kept["spec"].risk, kept["spec"].confirm = Risk.LOW, Confirm.NEVER  # tries to go silent afterwards
    assert reg.execute("s.t", {}).startswith("DENIED")  # still asks (no approver -> denied)
    assert kept["spec"].name == "t"  # and the plugin's own object was not re-prefixed


def test_MEM1_one_bad_entry_does_not_wipe_every_memory(tmp_path):
    import json

    from brok.memory import MemoryStore

    f = tmp_path / "memory.json"
    good = {"id": "a1", "kind": "longterm", "text": "keep me", "scope": "", "created": 1.0}
    f.write_text(json.dumps([good, {"id": "b2"}, "junk", {**good, "id": "c3", "from_the_future": 1}]))
    store = MemoryStore(f)
    assert sorted(i.id for i in store.list()) == ["a1", "c3"]
    store.add("longterm", "new note")  # a save after loading must not destroy the survivors
    assert {"a1", "c3"} <= {i.id for i in MemoryStore(f).list()}


def test_MEM2_unreadable_memory_file_is_kept_before_it_can_be_overwritten(tmp_path):
    from brok.memory import MemoryStore

    f = tmp_path / "memory.json"
    f.write_text("{not json")
    MemoryStore(f).add("longterm", "fresh")
    assert (tmp_path / "memory.json.corrupt").read_text() == "{not json"


# ================================================= 13. index / project / CLI
def test_IX1_index_ignores_symlinks_that_leave_the_project(tmp_path):
    from brok.agent.index import ProjectIndex

    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "diary.md").write_text("# class SecretDiary\nprivate")
    root = tmp_path / "proj"
    root.mkdir()
    (root / "a.py").write_text("def real_function():\n    pass\n")
    (root / "notes.md").symlink_to(outside / "diary.md")
    idx = ProjectIndex(str(root)).build()
    assert "a.py" in idx.files and "notes.md" not in idx.files
    assert "SecretDiary" not in idx.retrieve("secret diary class")


def test_IX2_line_count_matches_the_file(tmp_path):
    from brok.agent.index import ProjectIndex

    (tmp_path / "a.py").write_text("x = 1\ny = 2\n")
    assert ProjectIndex(str(tmp_path)).build().files["a.py"].lines == 2


def test_PJ1_dart_detection_does_not_overwrite_an_existing_build_system(tmp_path):
    from brok.agent.project import detect_project

    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
    (tmp_path / "pubspec.yaml").write_text("name: x\n")  # plain Dart, not Flutter
    assert detect_project(str(tmp_path)).build_system == "setuptools/pyproject"


def test_PJ2_requirements_options_are_not_dependencies(tmp_path):
    from brok.agent.project import detect_project

    (tmp_path / "requirements.txt").write_text("-r base.txt\n--index-url https://x\nrequests==2.0  # pinned\n")
    assert detect_project(str(tmp_path)).dependencies == ["requests==2.0"]


def test_CLI1_memory_add_without_text_prints_usage(capsys):
    from brok import cli

    assert cli.main(["memory", "add"]) == 1
    assert "Usage:" in capsys.readouterr().out


# ================================================= 14. local-only / OFFLINE honesty
def test_N1_github_poller_stays_silent_in_local_only_mode(qapp, monkeypatch):
    from brok import github_notify as gn

    settings = gn.GitHubSettings(enabled=True, token="tok", categories=("review_requested",))
    notifier = gn.GitHubNotifier(None, announcer=None, settings=settings, start_timer=False)
    launched = []
    monkeypatch.setattr(notifier, "launch", launched.append)
    monkeypatch.setattr(gn, "network_forbidden", lambda: False)
    assert notifier.active_sources() == {"notifications"}
    notifier.poll()
    assert launched == ["notifications"]
    launched.clear()
    monkeypatch.setattr(gn, "network_forbidden", lambda: True)  # local_only on (or the OFFLINE profile)
    assert notifier.active_sources() == set()
    notifier.poll()
    assert launched == []


def test_N2_network_forbidden_reads_the_local_only_setting(monkeypatch):
    from brok import config as brok_config
    from brok import github_notify as gn

    class Cfg:
        class ai:
            local_only = True

    monkeypatch.setattr(gn, "_local_only_cache", (-1e9, False))
    monkeypatch.setattr(brok_config.BrokConfig, "load", classmethod(lambda cls, *a, **k: Cfg()))
    assert gn.network_forbidden() is True


# ================================================= 15. calculator, notes, calendar
def test_CA1_calculator_cannot_be_used_to_exhaust_memory():
    from brok.agent.tools import ToolError
    from brok.productivity import calculate

    assert calculate("2**10 + 1") == "1025"
    with pytest.raises(ToolError):
        calculate("((10**1000)**1000)**1000")  # each exponent is small; the result would be ~10**9 digits
    with pytest.raises(ToolError):
        calculate("(9**1000)*(9**1000)*(9**1000)*(9**1000)*(9**1000)*(9**1000)*(9**1000)*(9**1000)*(9**1000)" * 40)


def test_NT1_a_note_is_always_one_numbered_line(tmp_path):
    from brok.agent.tools import ToolError
    from brok.productivity import Notes

    notes = Notes(tmp_path / "n.txt")
    notes.add("first\r\nline two")
    notes.add("with\u2028separator and \x0c form feed")
    assert notes.list().splitlines() == ["1. first line two", "2. with separator and   form feed"]
    with pytest.raises(ToolError):
        notes.add("   ")
    with pytest.raises(ToolError):
        notes.add("x" * 5000)


def test_ICS1_only_http_calendars_and_a_size_cap():
    from brok import calendar_ics

    assert "http" in calendar_ics.fetch_ics("file:///etc/passwd")["error"]

    class Resp:
        status, headers = 200, {}

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self, n=-1):
            return b"x" * (n if n > 0 else 10)

    result = calendar_ics.fetch_ics("https://example.test/c.ics", opener=lambda req, timeout: Resp())
    assert result["error"] == "calendar is too large" and result["ics_bytes"] == b""


def test_ICS2_prune_survives_a_uid_containing_a_pipe():
    from datetime import datetime, timedelta

    from brok.calendar_ics import ReminderTracker

    tr = ReminderTracker()
    now = datetime(2026, 10, 25, 12, 0).astimezone()
    old = (now - timedelta(days=3)).isoformat()
    fresh = (now + timedelta(hours=1)).isoformat()
    tr.fired = {f"uid|with|pipes|{old}", f"uid|with|pipes|{fresh}"} | {f"u{i}|{fresh}" for i in range(600)}
    tr.prune(now)
    assert f"uid|with|pipes|{old}" not in tr.fired and f"uid|with|pipes|{fresh}" in tr.fired


# ================================================= 16. reminders
def test_RM1_next_future_occurrence_matches_the_old_loop_and_is_instant():
    from datetime import datetime

    from brok.reminder import next_future_occurrence

    now = datetime(2026, 10, 25, 12, 0)
    assert next_future_occurrence(datetime(2026, 10, 25, 15, 0), now) == datetime(2026, 10, 25, 15, 0)
    assert next_future_occurrence(datetime(2026, 10, 25, 9, 0), now) == datetime(2026, 10, 26, 9, 0)
    assert next_future_occurrence(datetime(2026, 10, 25, 12, 0), now) == datetime(
        2026, 10, 26, 12, 0
    )  # == now: not future
    assert next_future_occurrence(datetime(1, 1, 1, 8, 0), now) == datetime(2026, 10, 26, 8, 0)  # corrupt value


def test_RM2_a_failing_flyby_still_advances_or_disables_the_reminder(monkeypatch):
    from datetime import datetime, timedelta

    from brok import reminder as rem

    saved = []
    monkeypatch.setattr(rem, "save_reminder", saved.append)
    ctl = rem.ReminderController.__new__(rem.ReminderController)

    def boom(r):
        raise RuntimeError("no display")

    ctl.show_flyby = boom
    past = datetime.now() - timedelta(minutes=5)
    ctl.reminder = rem.Reminder(fire_at=past, repeat_daily=False)
    ctl.fire()
    assert ctl.reminder.enabled is False  # a one-shot is finished even though the animation failed
    ctl.reminder = rem.Reminder(fire_at=past, repeat_daily=True)
    ctl.fire()
    assert ctl.reminder.fire_at > datetime.now() and len(saved) == 2


# ================================================= 17. every config.ini writer is atomic and private
def test_CW1_all_config_writers_go_through_the_safe_writer(tmp_path, monkeypatch):
    import os
    import stat

    from brok import llm_prompt

    monkeypatch.setattr(llm_prompt, "CFG_DIR", tmp_path)
    monkeypatch.setattr(llm_prompt, "CFG_FILE", tmp_path / "config.ini")
    llm_prompt.save_llm_enabled(True)
    llm_prompt.save_ollama_settings("http://127.0.0.1:11434", "model%1")  # a % in a value used to raise
    cfg = tmp_path / "config.ini"
    assert "model%1" in cfg.read_text() and not list(tmp_path.glob("*.tmp"))
    if os.name == "posix":
        assert stat.S_IMODE(os.stat(cfg).st_mode) == 0o600
