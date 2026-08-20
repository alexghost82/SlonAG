"""Shared provider protocols and request/response types.

Wave 3 adapters implement these protocols. This module does not call
network APIs or read secrets.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol, TypeAlias, runtime_checkable


@dataclass(frozen=True)
class ModelInfo:
    """Catalog entry for a single model and its capabilities."""

    provider_id: str
    model_id: str
    display_name: str
    text: bool = False
    streaming: bool = False
    structured_output: bool = False
    tool_calling: bool = False
    vision: bool = False
    audio_input: bool = False
    audio_output: bool = False
    embeddings: bool = False
    context_length: int = 0
    local: bool = False
    source: str = ""
    license: str = ""
    cost: float | None = None
    ram_gb: float | None = None
    vram_gb: float | None = None


@dataclass(frozen=True)
class ToolDefinition:
    """Provider-agnostic description of a tool available to a model."""

    name: str
    description: str
    parameters: Mapping[str, object]


@dataclass(frozen=True)
class ToolCall:
    """Provider-agnostic tool invocation requested by a model."""

    id: str
    name: str
    arguments: Mapping[str, object]

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("tool call id must be non-empty")
        if not self.name:
            raise ValueError("tool call name must be non-empty")
        if not isinstance(self.arguments, Mapping):
            raise TypeError("tool call arguments must be a mapping")


@dataclass(frozen=True)
class UserMessage:
    """Provider-neutral user text."""

    content: str
    role: str = field(default="user", init=False)


@dataclass(frozen=True)
class SystemMessage:
    """Provider-neutral system instruction."""

    content: str
    role: str = field(default="system", init=False)


@dataclass(frozen=True)
class AssistantMessage:
    """Completed assistant text without a tool request."""

    content: str = ""
    role: str = field(default="assistant", init=False)
    tool_calls: tuple[ToolCall, ...] = field(default=(), init=False)


@dataclass(frozen=True)
class AssistantToolCallMessage:
    """One native assistant turn containing one or more correlated tool calls."""

    tool_calls: tuple[ToolCall, ...]
    content: str = ""
    role: str = field(default="assistant", init=False)

    def __post_init__(self) -> None:
        if not self.tool_calls:
            raise ValueError("assistant tool-call message requires at least one call")


@dataclass(frozen=True)
class ToolResultMessage:
    """Native tool result correlated to the assistant request that produced it."""

    tool_call_id: str
    tool_name: str
    result: object | None = None
    error: str | None = None
    artifacts: tuple[object, ...] = ()
    role: str = field(default="tool", init=False)
    content: str = field(default="", init=False)

    @property
    def name(self) -> str:
        """Compatibility alias used by existing provider serializers."""
        return self.tool_name

    def __post_init__(self) -> None:
        if not self.tool_call_id:
            raise ValueError("tool result tool_call_id must be non-empty")
        if not self.tool_name:
            raise ValueError("tool result tool_name must be non-empty")
        if self.error is not None and self.result is not None:
            raise ValueError("tool result cannot contain both result and error")


@dataclass(frozen=True)
class ChatMessage:
    """Compatibility message accepted while callers migrate to typed messages."""

    role: str
    content: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str | None = None
    name: str | None = None
    result: object | None = None
    error: str | None = None
    artifacts: tuple[object, ...] = ()


ConversationMessage: TypeAlias = (
    UserMessage
    | SystemMessage
    | AssistantMessage
    | AssistantToolCallMessage
    | ToolResultMessage
    | ChatMessage
)


@dataclass(frozen=True)
class ChatRequest:
    """Provider-agnostic chat payload.

    ``role`` is the model role from settings (chat/planning/code/...) and is
    used for capability checks before a request is sent.
    """

    model: ModelInfo
    messages: Sequence[ConversationMessage]
    role: str = "chat"
    tools: Sequence[ToolDefinition] = ()
    tool_choice: str | None = None


@dataclass(frozen=True)
class ChatResponse:
    """Completed non-streaming chat result."""

    text: str
    provider_id: str
    model_id: str
    tool_calls: tuple[ToolCall, ...] = ()


@dataclass(frozen=True)
class ChatEvent:
    """One item in a unified chat stream.

    All providers emit the same shape: ``type`` is ``delta``, ``tool_call``,
    or ``done``. ``text`` holds an incremental chunk and ``tool_call`` holds
    a completed provider-agnostic invocation.
    """

    type: str
    text: str = ""
    tool_call: ToolCall | None = None
    tool_call_id: str | None = None
    tool_name: str | None = None
    arguments_delta: str = ""
    index: int | None = None

    def __post_init__(self) -> None:
        if self.type not in {"delta", "tool_call_delta", "tool_call", "done"}:
            raise ValueError(f"unsupported chat event type: {self.type!r}")
        if self.type == "tool_call" and self.tool_call is None:
            raise ValueError("completed tool_call event requires a ToolCall")


@dataclass(frozen=True)
class ProviderStatus:
    """Result of a credential or runtime health check."""

    provider_id: str
    ok: bool
    message: str = ""


@dataclass(frozen=True)
class VisionRequest:
    model: ModelInfo
    image: bytes
    prompt: str = ""


@dataclass(frozen=True)
class VisionResponse:
    text: str


@dataclass(frozen=True)
class AudioRequest:
    model: ModelInfo
    audio: bytes
    mime_type: str = "audio/wav"


@dataclass(frozen=True)
class Transcript:
    text: str


@dataclass(frozen=True)
class SpeechRequest:
    model: ModelInfo
    text: str


@dataclass(frozen=True)
class AudioStream:
    data: bytes
    mime_type: str = "audio/wav"


@runtime_checkable
class ChatProvider(Protocol):
    async def list_models(self) -> list[ModelInfo]: ...

    async def validate(self) -> ProviderStatus: ...

    async def chat(self, request: ChatRequest) -> ChatResponse: ...

    def stream(self, request: ChatRequest) -> AsyncIterator[ChatEvent]: ...


@runtime_checkable
class VisionProvider(Protocol):
    async def analyze(self, request: VisionRequest) -> VisionResponse: ...


@runtime_checkable
class SpeechToTextProvider(Protocol):
    async def transcribe(self, request: AudioRequest) -> Transcript: ...


@runtime_checkable
class TextToSpeechProvider(Protocol):
    async def synthesize(self, request: SpeechRequest) -> AudioStream: ...
