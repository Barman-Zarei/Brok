"""Maps application events to avatar states so UI code never contains animation logic."""

from __future__ import annotations

from .engine import AvatarEngine
from .states import AvatarState

_EVENTS = {
    "user_typing": AvatarState.TYPING,
    "listening": AvatarState.LISTENING,
    "ai_thinking": AvatarState.THINKING,
    "speaking": AvatarState.SPEAKING,
    "coding": AvatarState.CODING,
    "working": AvatarState.WORKING,
    "error": AvatarState.ERROR,
    "success": AvatarState.SUCCESS,
    "confused": AvatarState.CONFUSED,
    "happy": AvatarState.HAPPY,
    "notification": AvatarState.NOTIFICATION,
    "sleep": AvatarState.SLEEPING,
}


class AvatarManager:
    def __init__(self, engine: AvatarEngine) -> None:
        self.engine = engine

    def on_event(self, event: str) -> AvatarState:
        if event == "idle":
            self.engine.request(AvatarState.IDLE, force=True)
        elif event in _EVENTS:
            self.engine.request(_EVENTS[event])
        return self.engine.state

    def on_agent_event(self, kind: str, text: str = "") -> None:
        """Hook for AgentLoop(on_event=...): streaming text → speaking/typing, tool → coding/working."""
        if kind == "tool":
            self.on_event("coding" if any(k in text for k in ("write_file", "create_file", "run_tests")) else "working")
        elif kind == "text":
            self.on_event("speaking")
