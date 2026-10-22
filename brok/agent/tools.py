"""Tool registry with risk levels, schemas and a permission gate."""

from __future__ import annotations

import enum
import inspect
import logging
import threading
from dataclasses import dataclass
from typing import Any, Callable

from ..ai.messages import INVALID_ARGS_KEY, ToolSchema

logger = logging.getLogger(__name__)


class Risk(enum.IntEnum):
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4


class Confirm(enum.Enum):
    NEVER = "never"
    CONFIGURABLE = "configurable"  # asked unless the user enabled auto-approve for MEDIUM tools
    REQUIRED = "required"
    ALWAYS = "always"  # cannot be auto-approved by any setting


@dataclass
class ApprovalRequest:
    tool: str
    arguments: dict[str, Any]
    risk: Risk
    summary: str
    diff: str | None = None  # BEFORE/AFTER preview for edits


class ToolError(Exception):
    """Expected, model-visible failure (bad path, denied, ...)."""


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]
    risk: Risk
    confirm: Confirm
    func: Callable[..., str]
    # Optional dynamic override, e.g. run_command depends on the command text.
    dynamic: Callable[[dict[str, Any]], tuple[Risk, Confirm, str]] | None = None
    preview: Callable[[dict[str, Any]], str | None] | None = None
    # Runs BEFORE any approval prompt; returns an error string to refuse outright (e.g. blocked commands).
    precheck: Callable[[dict[str, Any]], str | None] | None = None


@dataclass
class PermissionPolicy:
    """Decides whether a tool call needs the user. Dangerous tools can never be silent."""

    auto_approve_medium: bool = False
    approver: Callable[[ApprovalRequest], bool] | None = None  # None => deny anything needing approval

    def needs_confirmation(self, risk: Risk, confirm: Confirm) -> bool:
        if confirm in (Confirm.ALWAYS, Confirm.REQUIRED):
            return True
        if risk >= Risk.HIGH:
            return True
        if confirm is Confirm.CONFIGURABLE:
            return not self.auto_approve_medium
        return False


def _tool_schema(spec: ToolSpec) -> ToolSchema:
    return ToolSchema(spec.name, spec.description, spec.parameters)


class ToolRegistry:
    def __init__(self, policy: PermissionPolicy | None = None) -> None:
        self.policy = policy or PermissionPolicy()
        self._tools: dict[str, ToolSpec] = {}
        self.cancel_event: threading.Event | None = None  # set by AgentLoop for the duration of a run

    def register(self, spec: ToolSpec) -> None:
        if spec.name in self._tools:
            raise ValueError(f"duplicate tool {spec.name}")
        self._tools[spec.name] = spec

    def names(self) -> list[str]:
        return sorted(self._tools)

    def get(self, name: str) -> ToolSpec:
        return self._tools[name]

    def schemas(self) -> list[ToolSchema]:
        return [_tool_schema(s) for s in self._tools.values()]

    def execute(self, name: str, arguments: dict[str, Any]) -> str:
        """Run a tool through the permission gate. Always returns text for the model."""
        spec = self._tools.get(name)
        if spec is None:
            return f"ERROR: unknown tool '{name}'"
        if not isinstance(arguments, dict):
            return f"ERROR: bad arguments for {name}: expected a JSON object"
        if INVALID_ARGS_KEY in arguments:
            return (
                f"ERROR: the arguments of {name} were not valid JSON (the reply may have been cut off). "
                "The tool was NOT run; send the call again with complete arguments."
            )
        try:
            # Check the call shape up front, so a TypeError raised *inside* a tool is a crash, not "bad arguments".
            inspect.signature(spec.func).bind(**arguments)
        except TypeError as exc:
            return f"ERROR: bad arguments for {name}: {exc}"
        except (ValueError, KeyError):  # signature not introspectable: fall through to the call itself
            pass
        try:
            if spec.precheck:
                refusal = spec.precheck(arguments)
                if refusal:
                    return f"ERROR: {refusal}"
            risk, confirm, why = spec.risk, spec.confirm, spec.description
            if spec.dynamic:
                risk, confirm, why = spec.dynamic(arguments)
            if self.policy.needs_confirmation(risk, confirm):
                diff = spec.preview(arguments) if spec.preview else None
                req = ApprovalRequest(name, arguments, risk, why, diff)
                if self.policy.approver is None or not self.policy.approver(req):
                    logger.info("tool %s denied (risk=%s)", name, risk.name)
                    return f"DENIED: the user did not approve '{name}'."
            logger.info("tool %s executing (risk=%s)", name, risk.name)
            return spec.func(**arguments)
        except ToolError as exc:
            return f"ERROR: {exc}"
        except Exception as exc:  # noqa: BLE001 - never crash the agent loop
            logger.exception("tool %s crashed", name)
            return f"ERROR: {type(exc).__name__}: {exc}"
