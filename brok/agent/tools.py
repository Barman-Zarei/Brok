"""Tool registry with risk levels, schemas and a permission gate."""

from __future__ import annotations

import enum
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from ..ai.messages import ToolSchema

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
    arguments: Dict[str, Any]
    risk: Risk
    summary: str
    diff: Optional[str] = None  # BEFORE/AFTER preview for edits


class ToolError(Exception):
    """Expected, model-visible failure (bad path, denied, ...)."""


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: Dict[str, Any]
    risk: Risk
    confirm: Confirm
    func: Callable[..., str]
    # Optional dynamic override, e.g. run_command depends on the command text.
    dynamic: Optional[Callable[[Dict[str, Any]], "tuple[Risk, Confirm, str]"]] = None
    preview: Optional[Callable[[Dict[str, Any]], Optional[str]]] = None


@dataclass
class PermissionPolicy:
    """Decides whether a tool call needs the user. Dangerous tools can never be silent."""

    auto_approve_medium: bool = False
    approver: Optional[Callable[[ApprovalRequest], bool]] = None  # None => deny anything needing approval

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
    def __init__(self, policy: Optional[PermissionPolicy] = None) -> None:
        self.policy = policy or PermissionPolicy()
        self._tools: Dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        if spec.name in self._tools:
            raise ValueError(f"duplicate tool {spec.name}")
        self._tools[spec.name] = spec

    def names(self) -> List[str]:
        return sorted(self._tools)

    def get(self, name: str) -> ToolSpec:
        return self._tools[name]

    def schemas(self) -> List[ToolSchema]:
        return [_tool_schema(s) for s in self._tools.values()]

    def execute(self, name: str, arguments: Dict[str, Any]) -> str:
        """Run a tool through the permission gate. Always returns text for the model."""
        spec = self._tools.get(name)
        if spec is None:
            return f"ERROR: unknown tool '{name}'"
        try:
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
        except TypeError as exc:
            return f"ERROR: bad arguments for {name}: {exc}"
        except Exception as exc:  # noqa: BLE001 - never crash the agent loop
            logger.exception("tool %s crashed", name)
            return f"ERROR: {type(exc).__name__}: {exc}"
