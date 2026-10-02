"""Structured logging with secret redaction. Never log secrets."""

from __future__ import annotations

import logging
import re

_PATTERNS = [
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{8,}"),
    re.compile(r"sk-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]{12,}"),
    re.compile(r"(?i)((?:api[_-]?key|token|secret|password)\s*[=:]\s*)[^\s'\",]{6,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
]


def redact(text: str) -> str:
    """Mask API keys / tokens in ``text``."""
    for pat in _PATTERNS:
        text = pat.sub(lambda m: (m.group(1) if m.lastindex else "") + "***REDACTED***", text)
    return text


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(record.getMessage())
        record.args = ()
        return True


def setup_logging(level: str = "INFO") -> None:
    """Root logger format: time level subsystem message (subsystem = logger name)."""
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    for h in root.handlers:
        if not any(isinstance(f, RedactingFilter) for f in h.filters):
            h.addFilter(RedactingFilter())
    if not root.handlers:
        h = logging.StreamHandler()
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s"))
        h.addFilter(RedactingFilter())
        root.addHandler(h)
