import os

import pytest

from brok import profile
from brok.config import BrokConfig


def test_default_profile_is_standard(monkeypatch):
    monkeypatch.delenv("BROK_PROFILE", raising=False)
    assert profile.active().name == profile.DEFAULT_PROFILE


def test_unknown_profile_falls_back(monkeypatch):
    monkeypatch.setenv("BROK_PROFILE", "nonsense")
    assert profile.active().name == profile.DEFAULT_PROFILE


def test_low_end_is_slower_and_quieter(monkeypatch):
    monkeypatch.setenv("BROK_PROFILE", "low-end")
    p = profile.active()
    assert p.tick_ms > 33 and not p.check_updates


def test_no_gpu_sets_software_render_env(monkeypatch):
    for k in ("QT_OPENGL", "QT_QUICK_BACKEND", "QT_XCB_FORCE_SOFTWARE_OPENGL", "LIBGL_ALWAYS_SOFTWARE"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("BROK_PROFILE", "no-gpu")
    profile.apply_environment()
    assert os.environ["QT_OPENGL"] == "software"
    for k in ("QT_OPENGL", "QT_QUICK_BACKEND", "QT_XCB_FORCE_SOFTWARE_OPENGL", "LIBGL_ALWAYS_SOFTWARE"):
        monkeypatch.delenv(k, raising=False)


def test_offline_forces_local_ai_even_if_file_says_claude(monkeypatch, tmp_path):
    monkeypatch.setenv("BROK_PROFILE", "offline")
    f = tmp_path / "brok.json"
    f.write_text('{"ai": {"provider": "claude", "local_only": false, "fallbacks": ["claude"]}}')
    cfg = BrokConfig.load(f, env={})
    assert cfg.ai.local_only and cfg.ai.provider == "ollama" and cfg.ai.fallbacks == ["ollama"]


@pytest.mark.parametrize("name", sorted(profile.PROFILES))
def test_every_profile_is_sane(name):
    p = profile.PROFILES[name]
    assert p.name == name and 16 <= p.tick_ms <= 200 and p.description
