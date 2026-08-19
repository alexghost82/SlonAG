"""Role-to-capability checks performed before a provider request."""

from __future__ import annotations

from collections.abc import Collection

from config.schema import MODEL_ROLE_KEYS

from providers.contracts import ModelInfo
from providers.errors import CapabilityError

ROLE_CAPABILITY_FLAGS: dict[str, str] = {
    "chat": "text",
    "planning": "text",
    "code": "text",
    "vision": "vision",
    "embeddings": "embeddings",
    "stt": "audio_input",
    "tts": "audio_output",
}

KNOWN_ROLES = frozenset(MODEL_ROLE_KEYS)


def supports(model: ModelInfo, role: str) -> bool:
    """Return True if ``model`` can serve ``role``."""
    flag = ROLE_CAPABILITY_FLAGS.get(role)
    if flag is None:
        return False
    return bool(getattr(model, flag))


def require_capability(model: ModelInfo, role: str) -> None:
    """Raise ``CapabilityError`` when ``model`` cannot serve ``role``.

    Call this before ``chat`` / ``stream`` (or other role-specific requests)
    so an unsupported assignment never becomes a provider call.
    """
    if not supports(model, role):
        raise CapabilityError(
            f"model {model.model_id!r} does not support role {role!r}",
            provider_id=model.provider_id,
            role=role,
            model_id=model.model_id,
        )


def require_capabilities(model: ModelInfo, required: Collection[str]) -> None:
    """Require every named capability before constructing a provider request.

    Capability names are :class:`ModelInfo` boolean fields. Unknown names are
    deliberately treated as unsupported, which keeps local model capability
    discovery conservative.
    """
    missing = tuple(
        capability
        for capability in dict.fromkeys(required)
        if not bool(getattr(model, capability, False))
    )
    if missing:
        names = ", ".join(repr(capability) for capability in missing)
        raise CapabilityError(
            f"model {model.model_id!r} does not support required capabilities: {names}",
            provider_id=model.provider_id,
            role=missing[0],
            model_id=model.model_id,
        )
