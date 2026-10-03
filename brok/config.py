"""Centralised BrokConfig. Secrets are never stored here (env / OS keyring only)."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any

from . import paths


@dataclass
class AIConfig:
    provider: str = "ollama"
    fallbacks: list[str] = field(default_factory=lambda: ["ollama"])
    local_only: bool = False
    claude_model: str = "claude-sonnet-5-5"
    ollama_host: str = "http://127.0.0.1:11434"
    ollama_model: str = "llama3.1"
    openai_model: str = "gpt-4o-mini"
    openai_base_url: str = "https://api.openai.com/v1"


@dataclass
class VoiceConfig:
    enabled: bool = False
    tts: str = "system"
    stt: str = "none"
    language: str = "fa"


@dataclass
class AvatarConfig:
    pack: str = "robot"
    theme: str = "cyan"


@dataclass
class MemoryConfig:
    enabled: bool = True
    store_conversations: bool = True


@dataclass
class GitHubConfig:
    enabled: bool = False


@dataclass
class WebConfig:
    search_provider: str = "none"  # "brave"


@dataclass
class SecurityConfig:
    auto_approve_medium: bool = False  # WRITE_FILE etc. skip the prompt when True
    diff_first: bool = True
    max_command_seconds: int = 120


@dataclass
class PrivacyConfig:
    log_files_sent: bool = True


@dataclass
class UIConfig:
    language: str = "fa"
    hotkey: str = "ctrl+space"


@dataclass
class NotificationsConfig:
    enabled: bool = True


@dataclass
class CodingConfig:
    max_iterations: int = 12
    timeout_seconds: int = 600
    token_budget: int = 200_000
    tool_budget: int = 60


@dataclass
class BrokConfig:
    ai: AIConfig = field(default_factory=AIConfig)
    voice: VoiceConfig = field(default_factory=VoiceConfig)
    avatar: AvatarConfig = field(default_factory=AvatarConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    github: GitHubConfig = field(default_factory=GitHubConfig)
    web: WebConfig = field(default_factory=WebConfig)
    security: SecurityConfig = field(default_factory=SecurityConfig)
    privacy: PrivacyConfig = field(default_factory=PrivacyConfig)
    ui: UIConfig = field(default_factory=UIConfig)
    notifications: NotificationsConfig = field(default_factory=NotificationsConfig)
    coding: CodingConfig = field(default_factory=CodingConfig)

    @staticmethod
    def default_path() -> Path:
        return paths.config_dir() / "brok.json"

    @classmethod
    def load(cls, path: Path | None = None, env: dict[str, Any] | None = None) -> BrokConfig:
        cfg = cls()
        p = Path(path) if path else cls.default_path()
        try:
            _merge(cfg, json.loads(p.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            pass
        apply_env(cfg, os.environ if env is None else env)
        return cfg

    def save(self, path: Path | None = None) -> Path:
        p = Path(path) if path else self.default_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False), encoding="utf-8")
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        tmp.replace(p)
        return p


def _merge(obj: Any, data: dict[str, Any]) -> None:
    for f in fields(obj):
        if f.name not in data:
            continue
        cur = getattr(obj, f.name)
        if is_dataclass(cur) and isinstance(data[f.name], dict):
            _merge(cur, data[f.name])
        elif isinstance(data[f.name], type(cur)) or cur is None:
            setattr(obj, f.name, data[f.name])


_ENV = {
    "BROK_AI_PROVIDER": ("ai", "provider", str),
    "BROK_LOCAL_ONLY": ("ai", "local_only", bool),
    "BROK_CLAUDE_MODEL": ("ai", "claude_model", str),
    "BROK_OLLAMA_HOST": ("ai", "ollama_host", str),
    "BROK_OLLAMA_MODEL": ("ai", "ollama_model", str),
    "BROK_LANGUAGE": ("ui", "language", str),
    "BROK_HOTKEY": ("ui", "hotkey", str),
}


def apply_env(cfg: BrokConfig, env: Mapping[str, str]) -> None:
    for var, (section, key, typ) in _ENV.items():
        if var in env:
            raw = env[var]
            setattr(getattr(cfg, section), key, raw.lower() in ("1", "true", "yes", "on") if typ is bool else raw)
