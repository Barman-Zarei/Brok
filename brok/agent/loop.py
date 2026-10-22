"""Bounded autonomous coding loop: observe → plan → act (tools) → read results → repeat → summarize.

Cancellation, the wall-clock deadline and the token budget are enforced *before every tool dispatch*, not only
around model turns. Tool calls that are not run still receive a tool result ("SKIPPED: …") so the history stays
valid for every provider, and every dispatched call is recorded in :attr:`AgentResult.effects` (state ``started``
before the call, ``finished`` after it) so an interrupted run can tell what really happened before it is retried.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from ..ai.messages import Message, ToolCall
from ..ai.orchestrator import AIOrchestrator
from ..ai.transport import ProviderError
from .tools import ToolRegistry

logger = logging.getLogger(__name__)

# Model stopped because it ran out of output tokens: text is cut off and tool arguments may be garbled.
TRUNCATED_STOP_REASONS = ("length", "max_tokens")
_STOP_TEXT = {"cancelled": "run cancelled", "timeout": "time limit reached", "token_budget": "token budget reached"}


@dataclass
class Limits:
    max_iterations: int = 12
    timeout_seconds: float = 600
    token_budget: int = 200_000  # rough (chars/4)
    tool_budget: int = 60


@dataclass
class AgentResult:
    # "done" | "max_iterations" | "timeout" | "token_budget" | "tool_budget" | "cancelled" | "truncated" | "error"
    status: str
    text: str = ""
    messages: list[Message] = field(default_factory=list)
    iterations: int = 0
    tool_calls: int = 0
    error: str = ""
    # One record per tool call of the run: {"id", "call_id", "name", "arguments", "state", "outcome"}.
    # state: "started" (dispatched, outcome unknown if the run died here) | "finished" | "skipped".
    effects: list[dict[str, Any]] = field(default_factory=list)


class AgentLoop:
    def __init__(
        self,
        orchestrator: AIOrchestrator,
        registry: ToolRegistry,
        limits: Limits | None = None,
        mode: str = "CODING",
        on_event: Callable[[str, str], None] | None = None,
        clock: Callable[[], float] = time.monotonic,
        on_effect: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.orch, self.registry = orchestrator, registry
        self.limits = limits or Limits()
        self.mode, self.on_event, self.clock = mode, on_event, clock
        self.on_effect = on_effect  # called with a copy of the effect record at every state change
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()
        self.orch.cancel()

    def _emit(self, kind: str, text: str) -> None:
        if self.on_event:
            try:
                self.on_event(kind, text)
            except Exception:  # noqa: BLE001 - a broken UI callback must not kill the run mid-batch
                logger.exception("on_event callback failed")

    def _note(self, effect: dict[str, Any]) -> None:
        if self.on_effect:
            try:
                self.on_effect(dict(effect))
            except Exception:  # noqa: BLE001
                logger.exception("on_effect callback failed")

    def _limit_status(self, start: float, tokens: int) -> str | None:
        if self.clock() - start > self.limits.timeout_seconds:
            return "timeout"
        if tokens > self.limits.token_budget:
            return "token_budget"
        return None

    @staticmethod
    def _unique_ids(calls: list[ToolCall], msgs: list[Message]) -> None:
        """Tool-call ids must be unique within a history (some providers send none, or restart numbering)."""
        used = {c.id for m in msgs for c in m.tool_calls}
        for c in calls:
            if not c.id or c.id in used:
                c.id = f"{c.id or 'call'}-{uuid.uuid4().hex[:6]}"
            used.add(c.id)

    def run(
        self, task: str, history: list[Message] | None = None, language: str = "", images: list[Any] | None = None
    ) -> AgentResult:
        # NOTE: the cancel flag is cleared when the run *ends*, not when it starts, so a cancel() that arrives
        # just before run() begins is honoured instead of being lost.
        try:
            return self._run(task, history, language, images)
        finally:
            self._cancel.clear()

    def _run(self, task: str, history: list[Message] | None, language: str, images: list[Any] | None) -> AgentResult:
        msgs = list(history or []) + [Message("user", task, images=list(images or []))]
        res = AgentResult("done", messages=msgs)
        run_id = uuid.uuid4().hex[:8]
        start, tokens = self.clock(), sum(len(m.content) for m in msgs) // 4
        schemas = self.registry.schemas()
        while True:
            if self._cancel.is_set():
                res.status = "cancelled"
                break
            if res.iterations >= self.limits.max_iterations:
                res.status = "max_iterations"
                break
            stop = self._limit_status(start, tokens)
            if stop:
                res.status = stop
                break
            res.iterations += 1
            text = ""
            stop_reason = ""
            calls: list[ToolCall] = []
            try:
                for ev in self.orch.stream(msgs, self.mode, schemas, language):
                    if self._cancel.is_set():
                        break
                    if ev.kind == "text":
                        text += ev.text
                        self._emit("text", ev.text)
                    elif ev.kind == "tool_call" and ev.tool_call:
                        calls.append(ev.tool_call)
                    elif ev.kind == "done":
                        stop_reason = ev.stop_reason
            except ProviderError as exc:
                res.status, res.error = "error", str(exc)
                break
            except Exception as exc:  # noqa: BLE001 - provider/transport bug or dropped connection: report, don't crash
                logger.exception("model stream crashed")
                res.status, res.error = "error", f"{type(exc).__name__}: {exc}"
                break
            if self._cancel.is_set():
                res.status = "cancelled"
                res.text = text or res.text
                break
            if stop_reason in TRUNCATED_STOP_REASONS:
                # Cut off by the output limit: the answer is incomplete and tool arguments may be garbled → run nothing.
                msgs.append(Message("assistant", text))
                res.text = text or res.text
                res.status = "truncated"
                res.error = "the model's reply was cut off by its output token limit"
                break
            if calls and self.clock() - start > self.limits.timeout_seconds:
                res.status = "timeout"  # the deadline passed while the model was answering: dispatch nothing
                res.text = text or res.text
                break
            self._unique_ids(calls, msgs)
            msgs.append(Message("assistant", text, calls))
            tokens += len(text) // 4
            res.text = text or res.text
            if not calls:
                break
            skip_with: str | None = None
            for call in calls:
                effect: dict[str, Any] = {
                    "id": f"{run_id}:{call.id}",
                    "call_id": call.id,
                    "name": call.name,
                    "arguments": call.arguments,
                    "state": "skipped",
                    "outcome": "",
                }
                if skip_with is None:  # re-checked before EVERY dispatch
                    stop = "cancelled" if self._cancel.is_set() else self._limit_status(start, tokens)
                    if stop:
                        res.status = stop
                        skip_with = f"SKIPPED: not executed ({_STOP_TEXT[stop]})."
                    elif res.tool_calls >= self.limits.tool_budget:
                        res.status = "tool_budget"
                        skip_with = "ERROR: tool budget exhausted"
                if skip_with is not None:
                    effect["outcome"] = skip_with
                    res.effects.append(effect)
                    self._note(effect)
                    msgs.append(Message("tool", skip_with, tool_call_id=call.id))
                    continue
                res.tool_calls += 1
                self._emit("tool", f"{call.name}({call.arguments})")
                effect["state"] = "started"  # recorded BEFORE the call: if we die here the effect is unknown
                res.effects.append(effect)
                self._note(effect)
                out = self.registry.execute(call.name, call.arguments)
                effect["state"], effect["outcome"] = "finished", out[:200]
                self._note(effect)
                if len(out) > 12000:
                    out = out[:6000] + "\n…[truncated]…\n" + out[-6000:]
                tokens += len(out) // 4
                msgs.append(Message("tool", out, tool_call_id=call.id))
            if res.status != "done":
                break
        res.messages = msgs
        return res
