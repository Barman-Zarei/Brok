"""Provider-neutral message types shared by every AI provider."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ImageInput:
    """An image attachment (screenshot, diagram, UI mock). ``data`` is base64."""

    data: str
    media_type: str = "image/png"


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Message:
    role: str  # "user" | "assistant" | "tool"
    content: str = ""
    tool_calls: List[ToolCall] = field(default_factory=list)
    tool_call_id: Optional[str] = None  # set on role == "tool"
    images: List[ImageInput] = field(default_factory=list)


@dataclass
class ToolSchema:
    """What the model sees about a tool (no permission info)."""

    name: str
    description: str
    parameters: Dict[str, Any]


@dataclass
class StreamEvent:
    kind: str  # "text" | "tool_call" | "done" | "error"
    text: str = ""
    tool_call: Optional[ToolCall] = None
    stop_reason: str = ""
