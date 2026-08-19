"""Local vision package. Importing this module registers factory id ``vision_local``."""

from __future__ import annotations

from providers.registry import register

from mark.vision.provider import (
    DEFAULT_KIND,
    DEFAULT_PRIVACY_PROFILE,
    PROVIDER_ID,
    UNTRUSTED_FENCE,
    UNTRUSTED_LABEL,
    VISION_KINDS,
    LocalVisionProvider,
    VisionEngine,
    VisionTaskRequest,
    engine_is_cloud,
    resolve_kind,
    wrap_untrusted_image_text,
)


def register_factory() -> None:
    """Register factory id ``vision_local``. Safe to call more than once."""
    register(PROVIDER_ID, LocalVisionProvider)


register_factory()

__all__ = [
    "DEFAULT_KIND",
    "DEFAULT_PRIVACY_PROFILE",
    "PROVIDER_ID",
    "UNTRUSTED_FENCE",
    "UNTRUSTED_LABEL",
    "VISION_KINDS",
    "LocalVisionProvider",
    "VisionEngine",
    "VisionTaskRequest",
    "engine_is_cloud",
    "register_factory",
    "resolve_kind",
    "wrap_untrusted_image_text",
]
