"""Bounded autonomous coding loop: observe → plan → act (tools) → read results → repeat → summarize."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

from ..ai.messages import Message
from ..ai.orchestrator import AIOrchestrator
from ..ai.transport import ProviderError
from .tools import ToolRegistry

logger = logging.getLogger(__name__)


@dataclass
class Limits:
    max_iterations: int = 12
    timeout_seconds: float = 600
    token_budget: int = 200_000  # rough (chars/4)
    tool_budget: int = 60


@dataclass
class AgentResult:
    status: str  # "done" | "max_iterations" | "timeout" | "token_budget" | "tool_budget" | "cancelled" | "error"
    text: str = ""
    messages: list[Message] = field(default_factory=list)
    iterations: int = 0
    tool_calls: int = 0
    error: str = ""


class AgentLoop:
    def __init__(
        self,
        orchestrator: AIOrchestrator,
        registry: ToolRegistry,
        limits: Limits | None = None,
        mode: str = "CODING",
        on_event: Callable[[str, str], None] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.orch, self.registry = orchestrator, registry
        self.limits = limits or Limits()
        self.mode, self.on_event, self.clock = mode, on_event, clock
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()
        self.orch.cancel()

    def _emit(self, kind: str, text: str) -> None:
        if self.on_event:
            self.on_event(kind, text)

    def run(self, task: str, history: list[Message] | None = None, language: str = "") -> AgentResult:
        self._cancel.clear()
        msgs = list(history or []) + [Message("user", task)]
        res = AgentResult("done", messages=msgs)
        start, tokens = self.clock(), sum(len(m.content) for m in msgs) // 4
        schemas = self.registry.schemas()
        while True:
            if self._cancel.is_set():
                res.status = "cancelled"
                break
            if res.iterations >= self.limits.max_iterations:
                res.status = "max_iterations"
                break
            if self.clock() - start > self.limits.timeout_seconds:
                res.status = "timeout"
                break
            if tokens > self.limits.token_budget:
                res.status = "token_budget"
                break
            res.iterations += 1
            text, calls = "", []  # type: str, List[ToolCall]
            try:
                for ev in self.orch.stream(msgs, self.mode, schemas, language):
                    if ev.kind == "text":
                        text += ev.text
                        self._emit("text", ev.text)
                    elif ev.kind == "tool_call" and ev.tool_call:
                        calls.append(ev.tool_call)
            except ProviderError as exc:
                res.status, res.error = "error", str(exc)
                break
            if self._cancel.is_set():
                res.status = "cancelled"
                res.text = text or res.text
                break
            msgs.append(Message("assistant", text, calls))
            tokens += len(text) // 4
            res.text = text or res.text
            if not calls:
                break
            for call in calls:
                if res.tool_calls >= self.limits.tool_budget:
                    msgs.append(Message("tool", "ERROR: tool budget exhausted", tool_call_id=call.id))
                    res.status = "tool_budget"
                    continue
                res.tool_calls += 1
                self._emit("tool", f"{call.name}({call.arguments})")
                out = self.registry.execute(call.name, call.arguments)
                if len(out) > 12000:
                    out = out[:6000] + "\n…[truncated]…\n" + out[-6000:]
                tokens += len(out) // 4
                msgs.append(Message("tool", out, tool_call_id=call.id))
            if res.status == "tool_budget":
                break
        res.messages = msgs
        return res
