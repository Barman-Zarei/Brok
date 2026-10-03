"""Inspectable memory: conversation, project, user preference, long-term. View/edit/delete/clear."""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Optional

from . import paths
from .logging_setup import redact

KINDS = ("conversation", "project", "preference", "longterm")


class SensitiveContentError(ValueError):
    """Raised when text looks like a secret; memory never silently stores those."""


@dataclass
class MemoryItem:
    id: str
    kind: str
    text: str
    scope: str = ""  # project path for kind == "project"
    created: float = 0.0


def looks_sensitive(text: str) -> bool:
    return redact(text) != text


class MemoryStore:
    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = Path(path) if path else paths.config_dir() / "memory.json"
        self._items: Dict[str, MemoryItem] = {}
        self._load()

    def _load(self) -> None:
        try:
            for d in json.loads(self.path.read_text(encoding="utf-8")):
                self._items[d["id"]] = MemoryItem(**d)
        except (OSError, ValueError, TypeError, KeyError):
            self._items = {}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps([asdict(i) for i in self._items.values()], ensure_ascii=False, indent=1), encoding="utf-8")
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        tmp.replace(self.path)

    def add(self, kind: str, text: str, scope: str = "") -> MemoryItem:
        if kind not in KINDS:
            raise ValueError(f"unknown memory kind: {kind}")
        if looks_sensitive(text):
            raise SensitiveContentError("this looks like a secret (API key/token/password); not stored")
        item = MemoryItem(uuid.uuid4().hex[:12], kind, text.strip(), scope, time.time())
        self._items[item.id] = item
        self._save()
        return item

    def list(self, kind: Optional[str] = None, scope: Optional[str] = None) -> List[MemoryItem]:
        out = [i for i in self._items.values() if (kind is None or i.kind == kind) and (scope is None or i.scope == scope)]
        return sorted(out, key=lambda i: i.created)

    def edit(self, item_id: str, text: str) -> MemoryItem:
        if looks_sensitive(text):
            raise SensitiveContentError("this looks like a secret; not stored")
        self._items[item_id].text = text.strip()
        self._save()
        return self._items[item_id]

    def delete(self, item_id: str) -> bool:
        gone = self._items.pop(item_id, None) is not None
        if gone:
            self._save()
        return gone

    def clear(self, kind: Optional[str] = None) -> int:
        ids = [i.id for i in self.list(kind)]
        for i in ids:
            del self._items[i]
        self._save()
        return len(ids)

    def context_for(self, project: str = "", limit_chars: int = 2000) -> str:
        """Memory to prepend to a prompt: preferences, long-term, and this project's notes."""
        parts: List[str] = []
        for i in self.list("preference") + self.list("longterm") + (self.list("project", project) if project else []):
            parts.append(f"- {i.text}")
        return "\n".join(parts)[:limit_chars]

    def counts(self) -> Dict[str, int]:
        return {k: len(self.list(k)) for k in KINDS}
