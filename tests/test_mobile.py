import os
import subprocess
import sys

from brok import mobile, paths


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


def test_config_dir_overrides(tmp_path, monkeypatch):
    monkeypatch.delenv("BROK_CONFIG_DIR", raising=False)
    monkeypatch.setenv("ANDROID_PRIVATE", str(tmp_path / "private"))
    assert paths.config_dir() == tmp_path / "private" / ".config" / "brok"
    monkeypatch.setenv("BROK_CONFIG_DIR", str(tmp_path / "explicit"))
    assert paths.config_dir() == tmp_path / "explicit"


def test_mobile_entry_does_not_need_pillow_or_desktop_hooks(tmp_path):
    """Pillow, pynput, Xlib and psutil have no Android/iOS wheels: the mobile entry point must start without them."""
    code = (
        "import sys\n"
        "for m in ('PIL', 'pynput', 'Xlib', 'psutil'):\n"
        "    sys.modules[m] = None\n"
        "from brok import mobile\n"
        "raise SystemExit(mobile.main(['brok'], auto_quit_ms=200))\n"
    )
    env = dict(os.environ, HOME=str(tmp_path), XDG_CONFIG_HOME=str(tmp_path), QT_QPA_PLATFORM="offscreen")
    result = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
