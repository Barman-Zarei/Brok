"""Privacy dashboard data: what Brok is doing, in one place."""

from __future__ import annotations

import threading
from dataclasses import dataclass


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
