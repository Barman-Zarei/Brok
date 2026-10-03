from __future__ import annotations

import os
import time

import pytest
from PySide6 import QtCore, QtWidgets

from brok.agent.builtin_tools import build_registry
from brok.agent.loop import Limits
from brok.agent.tools import PermissionPolicy
from brok.ai.messages import StreamEvent, ToolCall
from brok.ai.orchestrator import AIOrchestrator
from brok.avatar.states import AvatarState
from brok.workspace_ui import ApprovalDialog, WorkspaceWindow


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


class Scripted:
    name, is_local, supports_tools = "stub", True, True

    def __init__(self, turns):
        self.turns, self.seen = list(turns), []

    def chat(self, messages, system="", tools=None, cancel=None):
        self.seen.append(messages[-1].content)
        yield from self.turns.pop(0) if self.turns else [StreamEvent("text", text="تمام"), StreamEvent("done")]


def make_window(tmp_path, turns, approve):
    (tmp_path / "a.py").write_text("def f():\n    return 1\n")
    prov = Scripted(turns)
    orch = AIOrchestrator({"stub": prov}, "stub")

    def factory(root, approver):
        return build_registry(root, PermissionPolicy(approver=approver))

    w = WorkspaceWindow(str(tmp_path), orch, factory, Limits(max_iterations=4))
    w._show_approval = lambda req: approve(req)
    return w, prov


def wait_done(app, w, timeout=10):
    end = time.time() + timeout
    while w.worker is not None and time.time() < end:
        app.processEvents()
        time.sleep(0.01)
    app.processEvents()
    assert w.worker is None, "agent did not finish"


def test_panels_populate_and_file_open_save(app, tmp_path):
    w, _ = make_window(tmp_path, [], lambda r: True)
    assert "Python" in w.info_view.toPlainText()
    assert any("tests" in w.problems.item(i).text() for i in range(w.problems.count()))
    assert w.open_file(str(tmp_path / "a.py")) and "def f" in w.editor.toPlainText()
    w.editor.setPlainText("x = 2\n")
    assert w.save_file() and (tmp_path / "a.py").read_text() == "x = 2\n"
    assert w.badge.text().startswith("🟢")  # local provider is labelled LOCAL
    assert w.editor.layoutDirection() == QtCore.Qt.LeftToRight


def test_agent_edit_goes_through_diff_approval_apply(app, tmp_path):
    edit = [[StreamEvent("tool_call", tool_call=ToolCall("1", "write_file", {"path": "a.py", "content": "def f():\n    return 2\n"})),
             StreamEvent("done")], [StreamEvent("text", text="انجام شد"), StreamEvent("done")]]
    shown = []
    w, _ = make_window(tmp_path, edit, lambda r: shown.append(r) or True)
    w.open_file(str(tmp_path / "a.py"))
    w.input.setText("/code return 2 کن")
    w.send()
    wait_done(app, w)
    assert (tmp_path / "a.py").read_text().endswith("return 2\n")
    assert "-    return 1" in shown[0].diff and "+    return 2" in w.diff_view.toPlainText()
    assert "return 2" in w.editor.toPlainText()  # editor refreshed with the agent's change
    assert "انجام شد" in w.transcript.toPlainText() and w.avatar.engine.state is AvatarState.SUCCESS


def test_rejecting_the_diff_leaves_file_untouched(app, tmp_path):
    edit = [[StreamEvent("tool_call", tool_call=ToolCall("1", "write_file", {"path": "a.py", "content": "boom\n"})),
             StreamEvent("done")], [StreamEvent("text", text="باشه"), StreamEvent("done")]]
    w, _ = make_window(tmp_path, edit, lambda r: False)
    w.start_task("edit", "CODING")
    wait_done(app, w)
    assert "return 1" in (tmp_path / "a.py").read_text()


def test_quick_action_sends_selection_in_persian(app, tmp_path):
    w, prov = make_window(tmp_path, [], lambda r: True)
    w.open_file(str(tmp_path / "a.py"))
    w.editor.selectAll()
    w.quick_buttons["Explain"].click()
    wait_done(app, w)
    assert "این کد را توضیح بده" in prov.seen[0] and "def f" in prov.seen[0] and "a.py" in prov.seen[0]


def test_terminal_uses_the_sandbox(app, tmp_path):
    w, _ = make_window(tmp_path, [], lambda r: False)
    w.cmd_input.setText("rm -rf /")
    w.run_terminal_command()
    assert "blocked" in w.output.toPlainText()
    w.cmd_input.setText("git status")
    w.run_terminal_command()
    assert "exit=" in w.output.toPlainText()


def test_no_provider_shows_warning(app, tmp_path):
    (tmp_path / "a.py").write_text("x=1\n")
    orch = AIOrchestrator({"stub": Scripted([])}, "missing")
    w = WorkspaceWindow(str(tmp_path), orch, lambda r, a: build_registry(r, PermissionPolicy(approver=a)))
    assert "⚠" in w.badge.text()


def test_approval_dialog_defaults_to_reject(app):
    from brok.agent.tools import ApprovalRequest, Risk

    d = ApprovalDialog(ApprovalRequest("delete_file", {}, Risk.HIGH, "delete a.py", "-x\n+y\n"))
    btns = d.findChildren(QtWidgets.QPushButton)
    assert {b.text() for b in btns} >= {"Apply", "Reject"}
    assert any(b.isDefault() for b in btns)
