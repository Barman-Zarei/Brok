"""Provider-neutral message types shared by every AI provider."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ImageInput:
    """An image attachment (screenshot, diagram, UI mock). ``data`` is base64."""

    data: str
    media_type: str = "image/png"


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass
class Message:
    role: str  # "user" | "assistant" | "tool"
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str | None = None  # set on role == "tool"
    images: list[ImageInput] = field(default_factory=list)


@dataclass
class ToolSchema:
    """What the model sees about a tool (no permission info)."""

    name: str
    description: str
    parameters: dict[str, Any]


@dataclass
class StreamEvent:
    kind: str  # "text" | "tool_call" | "done" | "error"
    text: str = ""
    tool_call: ToolCall | None = None
    stop_reason: str = ""


# Providers put the raw text under this key when a tool call's arguments are not a valid JSON object (e.g. cut off
# by the output limit). The registry answers such a call with an error instead of running it with empty arguments.
INVALID_ARGS_KEY = "_brok_invalid_json"


def parse_tool_args(raw: str) -> dict[str, Any]:
    """Parse streamed tool arguments. Garbled/non-object JSON is flagged, never silently turned into ``{}``."""
    if not raw or not raw.strip():
        return {}
    try:
        val = json.loads(raw)
    except ValueError:
        return {INVALID_ARGS_KEY: raw[:2000]}
    return val if isinstance(val, dict) else {INVALID_ARGS_KEY: raw[:2000]}
