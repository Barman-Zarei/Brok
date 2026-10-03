"""Privacy dashboard data: what Brok is doing, in one place."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any


@dataclass
class PrivacyReport:
    provider: str
    mode: str  # "LOCAL AI" | "CLOUD AI"
    offline: bool
    network_requests: int
    cloud_chars_sent: int
    files_sent: list[str]
    memory_counts: dict[str, int]
    permissions: dict[str, bool]
    connected_accounts: list[str]


class PrivacyTracker:
    """Collects orchestrator/file-read events (wire ``on_send`` / ``on_file_read`` to it)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.provider, self.is_local = "", True
        self.requests = 0
        self.cloud_chars = 0
        self.files: list[str] = []

    def on_send(self, provider: str, is_local: bool, chars: int) -> None:
        with self._lock:
            self.provider, self.is_local = provider, is_local
            self.requests += 1
            if not is_local:
                self.cloud_chars += chars

    def on_file_read(self, rel_path: str, chars: int) -> None:
        with self._lock:
            if rel_path not in self.files:
                self.files.append(rel_path)

    def report(
        self,
        memory_counts: dict[str, int] | None = None,
        local_only: bool = False,
        auto_approve_medium: bool = False,
        accounts: list[str] | None = None,
    ) -> PrivacyReport:
        with self._lock:
            return PrivacyReport(
                provider=self.provider or "(none yet)",
                mode="LOCAL AI" if self.is_local else "CLOUD AI",
                offline=local_only,
                network_requests=self.requests,
                cloud_chars_sent=self.cloud_chars,
                files_sent=list(self.files),
                memory_counts=memory_counts or {},
                permissions={"auto_approve_file_edits": auto_approve_medium, "dangerous_tools_always_ask": True},
                connected_accounts=accounts or [],
            )


_shared: PrivacyTracker | None = None
_shared_lock = threading.Lock()


def get_tracker() -> PrivacyTracker:
    """The app-wide tracker, so the chat, the workspace and the dashboard all report the same facts."""
    global _shared
    with _shared_lock:
        if _shared is None:
            _shared = PrivacyTracker()
        return _shared


_ACCOUNTS = (
    ("Anthropic (Claude)", "ANTHROPIC_API_KEY", "anthropic_api_key"),
    ("OpenAI", "OPENAI_API_KEY", "openai_api_key"),
    ("GitHub", "GITHUB_TOKEN", "github_token"),
    ("Brave Search", "BRAVE_API_KEY", "brave_api_key"),
)


def connected_accounts() -> list[str]:
    """Names of services that have a credential configured (env var or OS keyring). Never returns the secrets."""
    import os

    from . import secret_store

    found = []
    for label, env, key in _ACCOUNTS:
        try:
            if os.environ.get(env) or secret_store.get_secret(key):
                found.append(label)
        except Exception:  # noqa: BLE001 - a broken keyring must not break the dashboard
            continue
    return found


def build_report(
    cfg: Any, tracker: PrivacyTracker | None = None, memory_counts: dict[str, int] | None = None
) -> PrivacyReport:
    """Assemble the dashboard data from config + live tracker (shared by the GUI panel and the CLI)."""
    tracker = tracker or get_tracker()
    if memory_counts is None:
        from .memory import MemoryStore

        memory_counts = MemoryStore().counts()
    rep = tracker.report(
        memory_counts=memory_counts,
        local_only=cfg.ai.local_only,
        auto_approve_medium=cfg.security.auto_approve_medium,
        accounts=connected_accounts(),
    )
    if rep.provider == "(none yet)":
        rep.provider = cfg.ai.provider
        rep.mode = "LOCAL AI" if cfg.ai.provider == "ollama" or cfg.ai.local_only else "CLOUD AI"
    return rep


def format_report(rep: PrivacyReport) -> str:
    mem = ", ".join(f"{k}: {v}" for k, v in rep.memory_counts.items()) or "empty"
    perms = "\n".join(f"  - {k}: {'ON' if v else 'OFF'}" for k, v in rep.permissions.items())
    files = "\n".join(f"  - {f}" for f in rep.files_sent[-20:]) or "  (none)"
    return (
        f"Provider: {rep.provider}  [{rep.mode}]{'  — OFFLINE/local-only' if rep.offline else ''}\n"
        f"AI requests this session: {rep.network_requests}\n"
        f"Characters sent to cloud this session: {rep.cloud_chars_sent}\n"
        f"Files read for the AI this session:\n{files}\n"
        f"Memory stored: {mem}\n"
        f"Permissions:\n{perms}\n"
        f"Connected accounts: {', '.join(rep.connected_accounts) or 'none'}\n"
        "Secrets live only in env vars / the OS keyring; they are never logged or written to memory."
    )
