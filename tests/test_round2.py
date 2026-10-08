from __future__ import annotations

import base64
import time

import pytest
from PIL import Image
from PySide2 import QtWidgets

from brok import chat_commands, llm_prompt
from brok.agent.builtin_tools import build_registry
from brok.agent.loop import Limits
from brok.agent.tools import PermissionPolicy
from brok.ai.messages import ImageInput, Message, StreamEvent
from brok.ai.orchestrator import AIOrchestrator
from brok.ai.transport import ProviderError
from brok.hotkey_qt import HotkeyBridge
from brok.memory import MemoryStore
from brok.workspace_ui import WorkspaceWindow


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


# ---------- memory in the desktop chat ----------
def test_chat_memory_commands(tmp_path):
    s = MemoryStore(tmp_path / "m.json")
    assert chat_commands.handle_chat_command("hello there", s, True) is None  # normal text goes to the AI
    r = chat_commands.handle_chat_command("/remember جواب‌ها کوتاه باشد", s, True)
    assert "Saved" in r and s.counts()["longterm"] == 1
    assert "کوتاه" in chat_commands.handle_chat_command("/memory", s, True)
    assert "Not saved" in chat_commands.handle_chat_command("/remember key sk-ant-abcdefghijklmnop", s, True)
    item_id = s.list()[0].id
    assert chat_commands.handle_chat_command(f"/forget {item_id}", s, True) == "Forgotten."
    assert "No memory" in chat_commands.handle_chat_command("/forget nope", s, True)
    assert "turned off" in chat_commands.handle_chat_command("/memory", s, False)
    assert "Cleared" in chat_commands.handle_chat_command("/forget-all", s, True)


def test_memory_injected_into_system_prompt(tmp_path, monkeypatch):
    s = MemoryStore(tmp_path / "m.json")
    s.add("longterm", "به فارسی ساده توضیح بده")
    monkeypatch.setattr("brok.chat_commands.MemoryStore", lambda: s)
    monkeypatch.setattr(
        "brok.chat_commands.BrokConfig.load",
        staticmethod(lambda *a, **k: type("C", (), {"memory": type("M", (), {"enabled": True})()})()),
    )
    prompt = llm_prompt.render_prompt([], 10)
    assert "به فارسی ساده توضیح بده" in prompt and "{{" not in prompt
    assert chat_commands.memory_block(s, False) == ""  # off => nothing injected


# ---------- hotkey ----------
def test_hotkey_bridge_opens_chat(app):
    calls = []

    class W:
        def show(self):
            calls.append("show")

        def raise_(self):
            calls.append("raise")

        def toggle_llm_chat(self):
            calls.append("chat")

    b = HotkeyBridge(W(), "ctrl+space")
    b.triggered.emit()
    app.processEvents()
    assert calls == ["show", "raise", "chat"]
    bad = HotkeyBridge(W(), "oops")
    assert bad.start() is False and "invalid" in bad.manager.status


# ---------- vision ----------
class Vis:
    name, is_local, supports_tools, supports_vision = "v", True, True, True

    def __init__(self):
        self.imgs = []

    def chat(self, messages, system="", tools=None, cancel=None):
        self.imgs = [i for m in messages for i in m.images]
        yield StreamEvent("text", text="دیدم")
        yield StreamEvent("done")


class Blind(Vis):
    name, supports_vision = "blind", False


def test_orchestrator_skips_non_vision_providers():
    v, b = Vis(), Blind()
    o = AIOrchestrator({"blind": b, "v": v}, "blind", ["v"])
    msgs = [Message("user", "look", images=[ImageInput("QUJD")])]
    assert [e.text for e in o.stream(msgs) if e.kind == "text"] == ["دیدم"] and v.imgs and not b.imgs
    only_blind = AIOrchestrator({"blind": b}, "blind")
    with pytest.raises(ProviderError):
        list(only_blind.stream(msgs))  # never silently drops the image


def make_window(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n")
    prov = Vis()
    orch = AIOrchestrator({"v": prov}, "v")
    w = WorkspaceWindow(
        str(tmp_path), orch, lambda r, a: build_registry(r, PermissionPolicy(approver=a)), Limits(max_iterations=3)
    )
    return w, prov


def wait_done(app, w):
    end = time.time() + 10
    while w.worker is not None and time.time() < end:
        app.processEvents()
        time.sleep(0.01)
    app.processEvents()
    assert w.worker is None


def test_workspace_attaches_image_and_sends_it(app, tmp_path):
    w, prov = make_window(tmp_path)
    img = tmp_path / "err.png"
    Image.new("RGB", (8, 8), "red").save(img)
    assert w.attach_image_file(str(img)) and "1" in w.images_label.text()
    assert not w.attach_image_file(str(tmp_path / "a.py"))  # not an image
    w.input.setText("این اسکرین‌شات خطا چیست؟")
    w.send()
    wait_done(app, w)
    assert len(prov.imgs) == 1 and base64.b64decode(prov.imgs[0].data)[:4] == b"\x89PNG"
    assert w.images_label.text() == "" and not w.pending_images  # consumed once


def test_screenshot_degrades_gracefully(app, tmp_path):
    w, _ = make_window(tmp_path)
    ok = w.attach_screenshot()  # offscreen may or may not provide a grab; must never raise
    assert ok in (True, False)
    if not ok:
        assert "not available" in w.output.toPlainText() or w.output.toPlainText()


# ---------- assistants panels ----------
def test_debugger_learning_health_panels(app, tmp_path):
    w, prov = make_window(tmp_path)
    seen = []
    orig = prov.chat
    prov.chat = lambda m, s="", t=None, c=None: (seen.append(m[-1].content), orig(m, s, t, c))[1]
    w.debug_input.setPlainText(
        "Traceback (most recent call last):\n  File \"a.py\", line 1, in <module>\nNameError: name 'y' is not defined"
    )
    w.run_debugger()
    wait_done(app, w)
    assert "NameError" in seen[0] and "RELEVANT SOURCE" in seen[0]
    w.learn_topic.setText("for loop")
    w.learn_step.setCurrentIndex(w.learn_step.findData("exercise"))
    w.run_learning()
    wait_done(app, w)
    assert "Do NOT include the solution" in seen[1] and "Persian" in seen[1]
    w.run_health()
    assert w.health_label.text() and w.tabs.currentWidget() is w.problems


def test_new_ui_strings_have_persian_translations():
    import json
    from pathlib import Path

    from brok import i18n

    base = Path(i18n.__file__).parent / "locale"
    en = json.loads((base / "en.json").read_text(encoding="utf-8"))["strings"]
    fa = json.loads((base / "fa.json").read_text(encoding="utf-8"))["strings"]
    assert set(en) == set(fa)
    for key in ("Attach image…", "AI Debugger", "Learning mode", "Teach me", "Coding Workspace…"):
        assert fa[key] != key and fa[key].strip()
