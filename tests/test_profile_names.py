"""BROK_PROFILE accepts the branch-style spelling (NO_GPU, low_end) as well as the profile name (no-gpu)."""

from __future__ import annotations

from brok import profile


def test_underscored_and_upper_case_profile_names_are_accepted(monkeypatch):
    monkeypatch.setenv("BROK_PROFILE", "NO_GPU")
    assert profile.active().name == "no-gpu"
    monkeypatch.setenv("BROK_PROFILE", "low_end")
    assert profile.active().name == "low-end"
    monkeypatch.setenv("BROK_PROFILE", "offline")
    assert profile.active().name == "offline"
