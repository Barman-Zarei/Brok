import os

from brok import mobile


def test_workspace_dir_is_created(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert mobile.workspace_dir().is_dir()


def test_mobile_app_starts_and_quits_headless(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    assert mobile.main(["brok"], auto_quit_ms=300) == 0
    assert os.environ["BROK_PROFILE"]  # the low-end profile is the mobile default
