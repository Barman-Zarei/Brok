"""Quick-command parser: /chat /code /fix /explain /test /run /search /git /github /remind /settings."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

COMMANDS = {
    "chat": "CHAT", "code": "CODING", "fix": "DEBUG", "explain": "CODING", "test": "CODING", "run": "AUTOMATION",
    "search": "RESEARCH", "git": "CODING", "github": "CODING", "remind": "AUTOMATION", "settings": "CHAT",
    "learn": "LEARNING",
}


@dataclass
class ParsedCommand:
    name: str  # command name, or "" for natural language
    args: str
    mode: str


def parse_command(line: str) -> Optional[ParsedCommand]:
    """``/fix this error`` → ParsedCommand('fix', 'this error', 'DEBUG'); natural language → mode inferred."""
    from .ai.orchestrator import infer_mode

    line = line.strip()
    if not line:
        return None
    if line.startswith("/"):
        name, _, rest = line[1:].partition(" ")
        name = name.lower()
        if name in COMMANDS:
            return ParsedCommand(name, rest.strip(), COMMANDS[name])
        return ParsedCommand("", line, infer_mode(line))  # unknown slash → treat as text
    return ParsedCommand("", line, infer_mode(line))
