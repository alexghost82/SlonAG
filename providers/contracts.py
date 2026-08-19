"""Shared provider protocols and request/response types.

Wave 3 adapters implement these protocols. This module does not call
network APIs or read secrets.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


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
class ChatMessage:
    """One turn in a chat request."""

    role: str
    content: str


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


@dataclass(frozen=True)
class ChatRequest:
    """Provider-agnostic chat payload.

    ``role`` is the model role from settings (chat/planning/code/...) and is
    used for capability checks before a request is sent.
    """

    model: ModelInfo
    messages: Sequence[ChatMessage]
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
