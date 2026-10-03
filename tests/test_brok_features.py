from __future__ import annotations

import json

import pytest

from brok.agent.builtin_tools import build_registry
from brok.agent.tools import Confirm, PermissionPolicy, Risk, ToolSpec
from brok.avatar.assets import build_legacy_zip, build_pack_dir, load_pack
from brok.avatar.engine import AvatarEngine
from brok.avatar.manager import AvatarManager
from brok.avatar.renderer import H, W, render_frame
from brok.avatar.states import AvatarState
from brok.github_agent import GitHubClient, register_github_tools
from brok.hotkey import HotkeyManager, to_pynput
from brok.plugins import Plugin, PluginManager
from brok.privacy import PrivacyTracker
from brok.productivity import Notes, calculate, register_productivity_tools
from brok.voice.providers import CommandSTT, VoicePipeline, VoiceUnavailable
from brok.web.search import SearchProvider, SearchResult, html_to_text, is_public_url, register_web_tools


def test_all_13_states_render_and_pack_roundtrip(tmp_path):
    assert len(AvatarState) == 13
    for st in AvatarState:
        im = render_frame(st, 1)
        assert im.size == (W, H) and im.getchannel("A").getbbox()  # not empty
    d = build_pack_dir(tmp_path / "p")
    assert set(load_pack(d)) == set(AvatarState)
    (d / "pack.json").write_text(json.dumps({"states": {"idle": "../evil.gif"}}))
    assert load_pack(d) is None  # path traversal / missing files rejected


def test_legacy_zip_matches_existing_char_format(tmp_path):
    import zipfile

    z = build_legacy_zip(tmp_path / "robot.zip")
    names = zipfile.ZipFile(z).namelist()
    assert "animation.gif" in names and "static.png" in names


def test_bundled_robot_is_default_and_loadable():
    from brok import char_catalog

    assert char_catalog.find_char("robot") is not None


def test_avatar_engine_priorities_and_timeouts():
    t = [0.0]
    e = AvatarEngine(lambda: t[0])
    m = AvatarManager(e)
    seen = []
    e.subscribe(lambda a, b: seen.append(b))
    assert m.on_event("ai_thinking") is AvatarState.THINKING
    m.on_event("error")
    assert m.on_event("user_typing") is AvatarState.ERROR  # error is not hidden by lower priority
    t[0] = 6
    assert e.tick() is AvatarState.IDLE  # error expires
    t[0] = 6 + 301
    assert e.tick() is AvatarState.SLEEPING
    m.on_agent_event("tool", "write_file({})")
    assert e.state is AvatarState.CODING


def test_persian_locale_complete_and_rtl():
    from brok import i18n

    assert "fa" in i18n.available_languages()
    en, fa = i18n.CATALOGS["en"], i18n.CATALOGS["fa"]
    assert set(fa) == set(en) and all(v.strip() for v in fa.values())
    assert i18n.is_rtl("fa") and not i18n.is_rtl("en")
    old = i18n.active_code
    try:
        i18n.active_code = "fa"
        assert i18n.tr("Settings") == "تنظیمات"
    finally:
        i18n.active_code = old


def test_rtl_layout_direction_applied():
    from PySide6 import QtCore, QtWidgets

    from brok import i18n

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    old = i18n.active_code
    try:
        i18n.active_code = "fa"
        i18n.apply_layout_direction(app)
        assert app.layoutDirection() == QtCore.Qt.RightToLeft
        i18n.active_code = "en"
        i18n.apply_layout_direction(app)
        assert app.layoutDirection() == QtCore.Qt.LeftToRight
    finally:
        i18n.active_code = old


# ---------- voice ----------
class FakeTTS:
    name = "fake"

    def __init__(self, ok=True, boom=False):
        self.ok, self.boom, self.said = ok, boom, []

    def available(self):
        return self.ok

    def speak(self, text, language="fa"):
        if self.boom:
            raise RuntimeError("audio device busy")
        self.said.append(text)


def test_voice_pipeline_and_graceful_fallback():
    ev = []
    tts = FakeTTS()
    p = VoicePipeline(None, tts, lambda q: "پاسخ:" + q, on_event=ev.append)
    assert p.respond("سلام") == "پاسخ:سلام" and tts.said == ["پاسخ:سلام"]
    assert ev == ["ai_thinking", "speaking", "idle"]
    p2 = VoicePipeline(None, FakeTTS(boom=True), lambda q: "x")
    assert p2.respond("hi") == "x" and "text only" in p2.notes[0]
    p3 = VoicePipeline(None, None, lambda q: "x")
    assert p3.respond("hi") == "x" and p3.notes
    with pytest.raises(VoiceUnavailable):
        p3.handle_audio()
    assert not CommandSTT("").available()


# ---------- privacy ----------
def test_privacy_report():
    t = PrivacyTracker()
    t.on_send("ollama", True, 100)
    t.on_send("claude", False, 500)
    t.on_file_read("a.py", 10)
    t.on_file_read("a.py", 10)
    r = t.report({"preference": 1}, local_only=False, accounts=["github"])
    assert r.mode == "CLOUD AI" and r.cloud_chars_sent == 500 and r.files_sent == ["a.py"] and r.network_requests == 2
    assert r.permissions["dangerous_tools_always_ask"]


def test_files_sent_tracking_through_tool(tmp_path):
    (tmp_path / "a.py").write_text("x=1\n")
    t = PrivacyTracker()
    reg = build_registry(str(tmp_path), PermissionPolicy(), on_file_read=t.on_file_read)
    reg.execute("read_file", {"path": "a.py"})
    assert t.files == ["a.py"]


# ---------- github ----------
class GHT:
    def __init__(self):
        self.posts = []

    def get_json(self, url, headers):
        if url.endswith("/issues?state=open"):
            return [{"number": 1, "title": "bug"}, {"number": 2, "title": "pr", "pull_request": {}}]
        return []

    def post_json(self, url, headers, body):
        self.posts.append((url, body))
        return {"number": 7, "html_url": "https://github.com/o/r/issues/7"}


def test_github_reads_free_writes_gated(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_" + "a" * 30)
    asked = []
    pol = PermissionPolicy(approver=lambda r: asked.append(r) or False, auto_approve_medium=True)
    reg = build_registry(str(tmp_path), pol)
    t = GHT()
    register_github_tools(reg, GitHubClient(transport=t))
    assert reg.execute("github_issues", {"repository": "o/r"}) == "#1 bug" and asked == []
    assert reg.execute("github_create_issue", {"repository": "o/r", "title": "x"}).startswith("DENIED")
    assert t.posts == [] and asked[0].risk is Risk.HIGH
    pol.approver = lambda r: True
    assert "issues/7" in reg.execute("github_create_issue", {"repository": "o/r", "title": "x"})
    assert "owner/name" in reg.execute("github_issues", {"repository": "../../x"})


def test_github_write_needs_token(tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    reg = build_registry(str(tmp_path), PermissionPolicy(approver=lambda r: True))
    register_github_tools(reg, GitHubClient(transport=GHT()))
    assert "token missing" in reg.execute("github_create_issue", {"repository": "o/r", "title": "x"})


# ---------- web ----------
@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/x",
        "http://localhost:8080",
        "file:///etc/passwd",
        "http://169.254.169.254/latest/meta-data",
        "ftp://a.b",
        "http://10.0.0.1",
    ],
)
def test_ssrf_guard(url):
    assert not is_public_url(url)


def test_html_to_text_and_offline_search(tmp_path):
    assert html_to_text("<p>hi</p><script>evil()</script><b>there</b>") == "hi\nthere"

    class P(SearchProvider):
        def search(self, q, limit=5):
            return [SearchResult("Doc", "https://docs.python.org", "official")]

    reg = build_registry(str(tmp_path), PermissionPolicy())
    register_web_tools(reg, P())
    assert "docs.python.org" in reg.execute("web_search", {"query": "x"})
    reg2 = build_registry(str(tmp_path), PermissionPolicy())
    register_web_tools(reg2, None)
    assert "offline" in reg2.execute("web_search", {"query": "x"})  # degrades, does not crash


# ---------- productivity ----------
def test_calculator_is_safe():
    assert calculate("2*(3+4)") == "14" and calculate("sqrt(16)+pi//1") == "7.0"
    for bad in ("__import__('os').system('x')", "().__class__", "open('f')", "9**9**9", "1/0"):
        with pytest.raises(Exception):
            calculate(bad)


def test_notes_tools(tmp_path):
    reg = build_registry(str(tmp_path), PermissionPolicy(auto_approve_medium=True))
    register_productivity_tools(reg, Notes(tmp_path / "n.txt"))
    assert reg.execute("list_notes", {}) == "no notes"
    reg.execute("add_note", {"text": "buy milk"})
    assert "1. buy milk" in reg.execute("list_notes", {})


# ---------- plugins ----------
class GoodPlugin(Plugin):
    name = "demo"

    def register(self, api):
        api.register_tool(
            ToolSpec("hello", "d", {"type": "object", "properties": {}}, Risk.LOW, Confirm.NEVER, lambda: "hi")
        )
        api.register_command("greet", lambda a: "hello " + a)


class BadPlugin(Plugin):
    name = "bad"

    def register(self, api):
        raise RuntimeError("boom")


def test_plugins_cannot_bypass_permissions_and_failures_are_isolated(tmp_path):
    asked = []
    reg = build_registry(str(tmp_path), PermissionPolicy(approver=lambda r: asked.append(r) or True))
    pm = PluginManager(reg)
    assert pm.load(GoodPlugin()) and not pm.load(BadPlugin())
    assert "boom" in pm.errors["bad"] and pm.commands["demo.greet"]("x") == "hello x"
    spec = reg.get("demo.hello")
    assert spec.risk >= Risk.MEDIUM and spec.confirm is not Confirm.NEVER  # floored
    assert reg.execute("demo.hello", {}) == "hi" and len(asked) == 1  # still asked


# ---------- hotkey ----------
def test_hotkey_parsing_and_graceful_failure():
    assert to_pynput("ctrl+space") == "<ctrl>+<space>" and to_pynput("Ctrl+Alt+b") == "<ctrl>+<alt>+b"
    for bad in ("space", "ctrl+", "ctrl+shift"):
        with pytest.raises(ValueError):
            to_pynput(bad)
    h = HotkeyManager("nonsense", lambda: None)
    assert h.start() is False and "invalid" in h.status
