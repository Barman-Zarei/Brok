from brok.config import BrokConfig
from brok.privacy import PrivacyTracker, build_report, format_report, get_tracker
from brok.quick import route


def test_plain_text_is_not_a_command():
    assert route("hello there") is None
    assert route("/unknowncmd x") is None


def test_help_and_usage():
    assert route("/help").kind == "reply"
    assert "Usage" in route("/fix").text


def test_windows_and_workspace_actions():
    assert route("/settings").action == "open_settings"
    assert route("/remind").action == "open_reminder"
    assert route("/privacy").action == "open_privacy"
    for c in ("/code", "/git", "/github", "/test", "/run"):
        assert route(c).action == "open_workspace"


def test_ai_rewrites():
    r = route("/fix NameError: x")
    assert r.kind == "ai" and "NameError: x" in r.text
    assert route("/explain foo").kind == "ai"


def test_search_is_a_background_task_and_degrades(monkeypatch):
    monkeypatch.delenv("BRAVE_API_KEY", raising=False)
    r = route("/search python 3.13")
    assert r.kind == "task" and r.func is not None
    assert "unavailable" in r.func() or "failed" in r.func()


def test_get_tracker_is_shared():
    assert get_tracker() is get_tracker()


def test_report_never_contains_secrets(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_SECRETSECRET")
    t = PrivacyTracker()
    t.on_send("claude", False, 120)
    t.on_file_read("src/a.py", 10)
    rep = build_report(BrokConfig(), t, memory_counts={"longterm": 1})
    text = format_report(rep)
    assert "GitHub" in rep.connected_accounts and "ghp_SECRETSECRET" not in text
    assert rep.mode == "CLOUD AI" and rep.cloud_chars_sent == 120 and "src/a.py" in text


def test_privacy_dialog_opens(qtbot=None):
    from PySide2 import QtWidgets

    from brok.privacy_ui import PrivacyDialog

    QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    d = PrivacyDialog()
    assert "Provider" in d.body.toPlainText()
