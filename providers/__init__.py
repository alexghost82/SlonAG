"""Provider contract layer.

Defines protocols, ``ModelInfo`` capabilities, typed errors, and a factory
registry. Real Gemini/OpenAI/OpenRouter/local adapters and the router live
in later waves.
"""

from providers.capabilities import require_capability, supports
from providers.contracts import (
    AssistantMessage,
    AssistantToolCallMessage,
    AudioRequest,
    AudioStream,
    ChatEvent,
    ChatMessage,
    ChatProvider,
    ChatRequest,
    ChatResponse,
    ConversationMessage,
    ModelInfo,
    ProviderStatus,
    SpeechRequest,
    SpeechToTextProvider,
    SystemMessage,
    TextToSpeechProvider,
    ToolResultMessage,
    Transcript,
    UserMessage,
    VisionProvider,
    VisionRequest,
    VisionResponse,
)
from providers.errors import (
    CapabilityError,
    ProviderAuthError,
    ProviderError,
    ProviderOfflineError,
)
from providers.registry import get, register, registered_ids

__all__ = [
    "AudioRequest",
    "AudioStream",
    "CapabilityError",
    "ChatEvent",
    "ChatMessage",
    "AssistantMessage",
    "AssistantToolCallMessage",
    "ChatProvider",
    "ChatRequest",
    "ChatResponse",
    "ConversationMessage",
    "ModelInfo",
    "ProviderAuthError",
    "ProviderError",
    "ProviderOfflineError",
    "ProviderStatus",
    "SystemMessage",
    "ToolResultMessage",
    "UserMessage",
    "SpeechRequest",
    "SpeechToTextProvider",
    "TextToSpeechProvider",
    "Transcript",
    "VisionProvider",
    "VisionRequest",
    "VisionResponse",
    "get",
    "register",
    "registered_ids",
    "require_capability",
    "supports",
]
