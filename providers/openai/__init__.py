"""OpenAI ChatProvider package.

Importing this package registers factory id ``openai``. The API key is
accepted only through ``OpenAIChatProvider(api_key=...)``.
"""

from providers.openai.provider import OpenAIChatProvider
from providers.registry import register

register("openai", OpenAIChatProvider)

__all__ = ["OpenAIChatProvider"]
