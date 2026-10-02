from __future__ import annotations

from brok import paths


def test_migrates_legacy_config_once(tmp_path, monkeypatch):
    monkeypatch.setattr(paths.Path, "home", classmethod(lambda cls: tmp_path))
    old = tmp_path / ".config" / "mycat"
    old.mkdir(parents=True)
    (old / "config.ini").write_text("[x]\na=1\n")
    assert paths.migrate_legacy_config() is True
    assert (tmp_path / ".config" / "brok" / "config.ini").read_text() == "[x]\na=1\n"
    assert (old / "config.ini").exists()  # legacy dir untouched
    assert paths.migrate_legacy_config() is False  # idempotent


def test_no_legacy_no_migration(tmp_path, monkeypatch):
    monkeypatch.setattr(paths.Path, "home", classmethod(lambda cls: tmp_path))
    assert paths.migrate_legacy_config() is False
