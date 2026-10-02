from .base import AIProvider
from .claude import ClaudeProvider
from .ollama import OllamaProvider
from .openai_compat import OpenAIProvider

#: Add a provider by registering its class here (or via a plugin).
PROVIDERS = {"claude": ClaudeProvider, "ollama": OllamaProvider, "openai": OpenAIProvider}

__all__ = ["AIProvider", "ClaudeProvider", "OllamaProvider", "OpenAIProvider", "PROVIDERS"]
