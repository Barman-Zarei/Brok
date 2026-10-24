"""Inspectable memory: conversation, project, user preference, long-term. View/edit/delete/clear."""

from __future__ import annotations

import builtins
import json
import logging
import os
import shutil
import time
import uuid
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from . import paths
from .logging_setup import redact

logger = logging.getLogger(__name__)

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
    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path else paths.config_dir() / "memory.json"
        self._items: dict[str, MemoryItem] = {}
        self._load()

    def _load(self) -> None:
        """Load what can be loaded. One bad entry (or a field from another version) must not discard everything:
        the next save would then overwrite the file and the user's memories would be gone for good."""
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except OSError:
            return  # no file yet
        except ValueError:
            self._keep_unreadable_copy()
            return
        if not isinstance(raw, list):
            self._keep_unreadable_copy()
            return
        known = {f.name for f in fields(MemoryItem)}
        for d in raw:
            try:
                self._items[d["id"]] = MemoryItem(**{k: v for k, v in d.items() if k in known})
            except (TypeError, KeyError, AttributeError):
                logger.warning("skipping an unreadable memory entry in %s", self.path)

    def _keep_unreadable_copy(self) -> None:
        backup = self.path.with_name(self.path.name + ".corrupt")
        try:
            shutil.copy2(self.path, backup)
            logger.warning("%s is unreadable; kept a copy as %s", self.path, backup)
        except OSError:
            pass

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        data = json.dumps([asdict(i) for i in self._items.values()], ensure_ascii=False, indent=1)
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)  # private from the first byte
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
            tmp.replace(self.path)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise

    def add(self, kind: str, text: str, scope: str = "") -> MemoryItem:
        if kind not in KINDS:
            raise ValueError(f"unknown memory kind: {kind}")
        if looks_sensitive(text):
            raise SensitiveContentError("this looks like a secret (API key/token/password); not stored")
        item = MemoryItem(uuid.uuid4().hex[:12], kind, text.strip(), scope, time.time())
        self._items[item.id] = item
        self._save()
        return item

    def list(self, kind: str | None = None, scope: str | None = None) -> builtins.list[MemoryItem]:
        out = [
            i for i in self._items.values() if (kind is None or i.kind == kind) and (scope is None or i.scope == scope)
        ]
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

    def clear(self, kind: str | None = None) -> int:
        ids = [i.id for i in self.list(kind)]
        for i in ids:
            del self._items[i]
        self._save()
        return len(ids)

    def context_for(self, project: str = "", limit_chars: int = 2000) -> str:
        """Memory to prepend to a prompt: preferences, long-term, and this project's notes."""
        items = self.list("preference") + self.list("longterm") + (self.list("project", project) if project else [])
        parts = [f"- {i.text}" for i in items]
        return "\n".join(parts)[:limit_chars]

    def counts(self) -> dict[str, int]:
        return {k: len(self.list(k)) for k in KINDS}
