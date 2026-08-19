"""OpenRouter chat adapter. Importing this package registers ``openrouter``."""

from providers.openrouter.client import DEFAULT_API_URL
from providers.openrouter.errors import RateLimitError
from providers.openrouter.provider import OpenRouterChatProvider
from providers.registry import register


def register_provider() -> None:
    """Register the OpenRouter factory as ``openrouter``."""
    register("openrouter", OpenRouterChatProvider)


register_provider()

__all__ = [
    "DEFAULT_API_URL",
    "OpenRouterChatProvider",
    "RateLimitError",
    "register_provider",
]
