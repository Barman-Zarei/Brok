"""Wiring: BrokConfig -> providers -> orchestrator -> tool registry. Shared by the CLI and the GUI."""

from __future__ import annotations

from typing import Callable

from . import secret_store
from .agent.builtin_tools import build_registry
from .agent.tools import PermissionPolicy, ToolRegistry
from .ai.orchestrator import AIOrchestrator
from .ai.personality import Personality
from .ai.providers import ClaudeProvider, OllamaProvider, OpenAIProvider
from .config import BrokConfig
from .github_agent import GitHubClient, register_github_tools
from .privacy import PrivacyTracker
from .productivity import Notes, register_productivity_tools
from .web.search import BraveSearchProvider, register_web_tools


def build_orchestrator(cfg: BrokConfig, tracker: PrivacyTracker | None = None) -> AIOrchestrator:
    a = cfg.ai
    providers = {
        "claude": ClaudeProvider(a.claude_model, key_resolver=lambda: secret_store.get_secret("anthropic_api_key")),
        "ollama": OllamaProvider(a.ollama_model, a.ollama_host),
        "openai": OpenAIProvider(
            a.openai_model, a.openai_base_url, key_resolver=lambda: secret_store.get_secret("openai_api_key")
        ),
    }
    return AIOrchestrator(
        providers,
        a.provider,
        a.fallbacks,
        a.local_only,
        Personality(default_language=cfg.ui.language),
        on_send=tracker.on_send if tracker else None,
    )


def build_tools(
    cfg: BrokConfig, root: str, approver: Callable | None = None, tracker: PrivacyTracker | None = None
) -> ToolRegistry:
    from .paths import config_dir

    policy = PermissionPolicy(auto_approve_medium=cfg.security.auto_approve_medium, approver=approver)
    reg = build_registry(
        root, policy, cfg.security.max_command_seconds, on_file_read=tracker.on_file_read if tracker else None
    )
    register_productivity_tools(reg, Notes(config_dir() / "notes.txt"))
    if not cfg.ai.local_only:  # offline/local-only: no network tools are even offered to the model
        if cfg.github.enabled:
            register_github_tools(reg, GitHubClient(lambda: secret_store.get_secret("github_token")))
        if cfg.web.search_provider == "brave":
            register_web_tools(reg, BraveSearchProvider(lambda: secret_store.get_secret("brave_api_key")))
    return reg
