"""Named fallback policies that satisfy ``providers.router.FallbackPolicy``.

Local → cloud is never a silent default. Only ``preselected_cloud`` and an
explicit user-allowed ``cost_or_speed`` object with ``requires_confirmation=True``
may return a cloud id after a local failure. This module does not call
providers and does not walk a hidden model list.
"""

from __future__ import annotations

from typing import Any

from config.schema import NETWORK_MODES, PRIVACY_PROFILES
from providers.errors import ProviderError
from providers.router import CLOUD_PROVIDER_IDS, LOCAL_PROVIDER_IDS, FallbackPolicy

POLICY_NEVER = "never"
POLICY_SAME_PROVIDER = "same_provider"
POLICY_LOCAL_ONLY = "local_only"
POLICY_PRESELECTED_CLOUD = "preselected_cloud"
POLICY_COST_OR_SPEED = "cost_or_speed"

POLICY_NAMES = frozenset(
    {
        POLICY_NEVER,
        POLICY_SAME_PROVIDER,
        POLICY_LOCAL_ONLY,
        POLICY_PRESELECTED_CLOUD,
        POLICY_COST_OR_SPEED,
    }
)

_PREFER_VALUES = frozenset({"cost", "speed"})


def is_cloud_provider(provider_id: str) -> bool:
    return provider_id in CLOUD_PROVIDER_IDS


def is_local_provider(provider_id: str) -> bool:
    return provider_id in LOCAL_PROVIDER_IDS


class NeverFallbackPolicy:
    """Named ``never`` policy. Offline-equivalent: never returns a cloud id."""

    name = POLICY_NEVER
    requires_confirmation = False

    def next(self, failed_provider_id: str, error: BaseException) -> str | None:
        return None


class SameProviderFallbackPolicy:
    """Stay inside the failed provider. No hidden model list exists.

    An optional ``alternate_provider_id`` is accepted only when it equals the
    failed provider. Because this module does not invent another model, and the
    router will not retry the same provider id, ``next`` returns ``None`` when
    no real same-provider alternate exists.
    """

    name = POLICY_SAME_PROVIDER
    requires_confirmation = False

    def __init__(self, alternate_provider_id: str | None = None) -> None:
        self.alternate_provider_id = alternate_provider_id

    def next(self, failed_provider_id: str, error: BaseException) -> str | None:
        if self.alternate_provider_id is None:
            return None
        if self.alternate_provider_id != failed_provider_id:
            return None
        return None


class LocalOnlyFallbackPolicy:
    """Fall back only to an explicit local provider. Never returns a cloud id."""

    name = POLICY_LOCAL_ONLY
    requires_confirmation = False

    def __init__(self, local_provider_id: str = "local") -> None:
        if is_cloud_provider(local_provider_id):
            raise ProviderError(
                "local_only cannot target a cloud provider",
                provider_id=local_provider_id,
            )
        if not local_provider_id.strip():
            raise ProviderError("local_provider_id must be a non-empty string")
        self.local_provider_id = local_provider_id

    def next(self, failed_provider_id: str, error: BaseException) -> str | None:
        if is_cloud_provider(self.local_provider_id):
            return None
        if failed_provider_id == self.local_provider_id:
            return None
        if is_cloud_provider(failed_provider_id):
            return self.local_provider_id
        if is_local_provider(failed_provider_id):
            return self.local_provider_id
        return self.local_provider_id


class PreselectedCloudFallbackPolicy:
    """Fall back to one caller-selected cloud provider.

    This is an explicit local → cloud policy. Confirmation is recorded on the
    object so a later UI can prompt before the router is invoked.
    """

    name = POLICY_PRESELECTED_CLOUD

    def __init__(
        self,
        cloud_provider_id: str,
        *,
        requires_confirmation: bool = True,
    ) -> None:
        if cloud_provider_id not in CLOUD_PROVIDER_IDS:
            raise ProviderError(
                "preselected_cloud requires a known cloud provider",
                provider_id=cloud_provider_id,
            )
        self.cloud_provider_id = cloud_provider_id
        self.requires_confirmation = requires_confirmation

    def next(self, failed_provider_id: str, error: BaseException) -> str | None:
        if failed_provider_id == self.cloud_provider_id:
            return None
        return self.cloud_provider_id


class CostOrSpeedFallbackPolicy:
    """Fall back to one explicit cheaper or faster provider.

    This policy does not rank providers and does not invent a catalog. Local →
    cloud is allowed only when the caller sets ``allow_local_to_cloud=True``
    and records ``requires_confirmation=True``.
    """

    name = POLICY_COST_OR_SPEED

    def __init__(
        self,
        target_provider_id: str | None = None,
        *,
        prefer: str = "cost",
        allow_local_to_cloud: bool = False,
        requires_confirmation: bool = True,
    ) -> None:
        if prefer not in _PREFER_VALUES:
            raise ProviderError("prefer must be 'cost' or 'speed'")
        self.target_provider_id = target_provider_id
        self.prefer = prefer
        self.allow_local_to_cloud = allow_local_to_cloud
        self.requires_confirmation = requires_confirmation

    def next(self, failed_provider_id: str, error: BaseException) -> str | None:
        target = self.target_provider_id
        if target is None or target == failed_provider_id:
            return None
        if is_local_provider(failed_provider_id) and is_cloud_provider(target):
            if not self.allow_local_to_cloud:
                return None
            if not self.requires_confirmation:
                return None
            return target
        return target


def create_policy(name: str, **kwargs: Any) -> FallbackPolicy:
    """Construct a named policy. Unknown names are rejected."""
    normalized = name.strip().lower().replace("-", "_")
    if normalized == POLICY_NEVER:
        return NeverFallbackPolicy()
    if normalized == POLICY_SAME_PROVIDER:
        alternate = kwargs.get("alternate_provider_id")
        if alternate is not None and not isinstance(alternate, str):
            raise ProviderError("alternate_provider_id must be a string")
        return SameProviderFallbackPolicy(alternate_provider_id=alternate)
    if normalized == POLICY_LOCAL_ONLY:
        local_id = kwargs.get("local_provider_id", "local")
        if not isinstance(local_id, str):
            raise ProviderError("local_provider_id must be a string")
        return LocalOnlyFallbackPolicy(local_provider_id=local_id)
    if normalized == POLICY_PRESELECTED_CLOUD:
        cloud_id = kwargs.get("cloud_provider_id")
        if not isinstance(cloud_id, str) or not cloud_id.strip():
            raise ProviderError("preselected_cloud requires cloud_provider_id")
        confirmation = kwargs.get("requires_confirmation", True)
        if not isinstance(confirmation, bool):
            raise ProviderError("requires_confirmation must be a bool")
        return PreselectedCloudFallbackPolicy(
            cloud_id, requires_confirmation=confirmation
        )
    if normalized == POLICY_COST_OR_SPEED:
        target = kwargs.get("target_provider_id")
        if target is not None and not isinstance(target, str):
            raise ProviderError("target_provider_id must be a string")
        prefer = kwargs.get("prefer", "cost")
        if not isinstance(prefer, str):
            raise ProviderError("prefer must be a string")
        allow = kwargs.get("allow_local_to_cloud", False)
        confirmation = kwargs.get("requires_confirmation", True)
        if not isinstance(allow, bool) or not isinstance(confirmation, bool):
            raise ProviderError("allow_local_to_cloud and requires_confirmation must be bool")
        return CostOrSpeedFallbackPolicy(
            target_provider_id=target,
            prefer=prefer,
            allow_local_to_cloud=allow,
            requires_confirmation=confirmation,
        )
    raise ProviderError(f"unknown fallback policy {name!r}")


def resolve_policy(
    name: str,
    *,
    network_mode: str | None = None,
    privacy_profile: str | None = None,
    **kwargs: Any,
) -> FallbackPolicy:
    """Return a named policy, or the offline-equivalent ``never`` policy.

    ``network_mode='offline'`` and ``privacy_profile='fully_local'`` never
    yield a policy that can return a cloud id.
    """
    if network_mode is not None and network_mode not in NETWORK_MODES:
        raise ProviderError("network_mode has an unsupported value")
    if privacy_profile is not None and privacy_profile not in PRIVACY_PROFILES:
        raise ProviderError("privacy_profile has an unsupported value")
    if network_mode == "offline" or privacy_profile == "fully_local":
        return NeverFallbackPolicy()
    return create_policy(name, **kwargs)


__all__ = [
    "POLICY_COST_OR_SPEED",
    "POLICY_LOCAL_ONLY",
    "POLICY_NAMES",
    "POLICY_NEVER",
    "POLICY_PRESELECTED_CLOUD",
    "POLICY_SAME_PROVIDER",
    "CostOrSpeedFallbackPolicy",
    "LocalOnlyFallbackPolicy",
    "NeverFallbackPolicy",
    "PreselectedCloudFallbackPolicy",
    "SameProviderFallbackPolicy",
    "create_policy",
    "is_cloud_provider",
    "is_local_provider",
    "resolve_policy",
]
