"""Plugin architecture: plugins register tools/commands through a narrow API; risk can never be lowered."""

from __future__ import annotations

import dataclasses
import logging
from abc import ABC, abstractmethod
from typing import Any, Callable

from .agent.tools import Confirm, Risk, ToolRegistry, ToolSpec

logger = logging.getLogger(__name__)
ENTRY_POINT_GROUP = "brok.plugins"


class PluginAPI:
    def __init__(self, registry: ToolRegistry, plugin_name: str) -> None:
        self._reg, self._plugin = registry, plugin_name
        self.registered: list[str] = []
        self.commands: dict[str, Callable[[str], str]] = {}

    def register_tool(self, spec: ToolSpec) -> None:
        # Third-party tools are never silent: floor MEDIUM risk and at least configurable confirmation.
        # Register a COPY: the plugin keeps its own reference, and lowering `risk`/`confirm` on it afterwards (or
        # registering one spec twice, which re-prefixed the name) must not change what the registry enforces.
        spec = dataclasses.replace(
            spec,
            name=f"{self._plugin}.{spec.name}",
            risk=max(spec.risk, Risk.MEDIUM),
            confirm=Confirm.CONFIGURABLE if spec.confirm is Confirm.NEVER else spec.confirm,
        )
        self._reg.register(spec)
        self.registered.append(spec.name)

    def register_command(self, name: str, fn: Callable[[str], str]) -> None:
        self.commands[f"{self._plugin}.{name}"] = fn


class Plugin(ABC):
    name = "plugin"

    @abstractmethod
    def register(self, api: PluginAPI) -> None: ...


class PluginManager:
    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry
        self.loaded: list[str] = []
        self.errors: dict[str, str] = {}
        self.commands: dict[str, Callable[[str], str]] = {}

    def load(self, plugin: Plugin) -> bool:
        """A broken plugin must never take the app down."""
        api = PluginAPI(self.registry, plugin.name)
        try:
            plugin.register(api)
            self.commands.update(api.commands)
            self.loaded.append(plugin.name)
            return True
        except Exception as exc:  # noqa: BLE001
            for name in api.registered:  # a half-registered plugin must not leave callable tools behind
                self.registry.unregister(name)
            self.errors[plugin.name] = str(exc)
            logger.warning("plugin %s failed: %s", plugin.name, exc)
            return False

    def load_entry_points(self) -> None:
        try:
            from importlib import metadata

            eps: Any = metadata.entry_points()
            group = eps.select(group=ENTRY_POINT_GROUP) if hasattr(eps, "select") else eps.get(ENTRY_POINT_GROUP, [])
            for ep in group:
                try:
                    self.load(ep.load()())
                except Exception as exc:  # noqa: BLE001
                    self.errors[ep.name] = str(exc)
        except Exception as exc:  # noqa: BLE001
            logger.warning("plugin discovery failed: %s", exc)
