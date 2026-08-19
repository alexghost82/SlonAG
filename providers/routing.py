"""Deterministic model routing with privacy and capability hard constraints."""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence

from providers.capabilities import supports
from providers.contracts import ModelInfo
from providers.errors import CapabilityError, ProviderError

CLOUD_PROVIDER_IDS = frozenset({"gemini", "openai", "openrouter"})
LOCAL_PROVIDER_IDS = frozenset({"local", "ollama", "llama_cpp"})
ROUTING_MODES = frozenset({"manual", "local_first", "local_only", "cloud_first"})

Availability = Mapping[object, bool] | None

_LOCAL_PREFERENCE_WEIGHT = 1_000_000_000.0
_UNKNOWN_COST = 1_000_000.0


def is_local_model(model: ModelInfo) -> bool:
    """Return whether a catalog entry belongs to a supported local runtime."""
    return model.provider_id in LOCAL_PROVIDER_IDS


def score_model(
    model: ModelInfo,
    *,
    required_capabilities: frozenset[str],
    prefer_local: bool,
    privacy_profile: str,
    availability: bool,
) -> float:
    """Score a model only after enforcing routing hard constraints.

    A higher score is preferred.  Invalid models are rejected rather than
    assigned a low score so capability, privacy, and availability can never be
    traded for cost.  Unknown cost sorts after a known cost while remaining a
    usable candidate.
    """
    missing = tuple(
        capability
        for capability in sorted(required_capabilities)
        if not bool(getattr(model, capability, False))
    )
    if missing:
        raise CapabilityError(
            f"model does not support required capabilities: {', '.join(missing)}",
            provider_id=model.provider_id,
            model_id=model.model_id,
        )
    if not availability:
        raise CapabilityError(
            "model is unavailable",
            provider_id=model.provider_id,
            model_id=model.model_id,
        )
    if privacy_profile in {"fully_local", "local_with_tools"} and not is_local_model(
        model
    ):
        raise CapabilityError(
            f"model is not permitted by privacy profile {privacy_profile!r}",
            provider_id=model.provider_id,
            model_id=model.model_id,
        )

    estimated_cost = _UNKNOWN_COST if model.cost is None else max(model.cost, 0.0)
    local_preference = (
        _LOCAL_PREFERENCE_WEIGHT if prefer_local and is_local_model(model) else 0.0
    )
    return local_preference - estimated_cost


def select_model(
    candidates: Sequence[ModelInfo],
    *,
    routing_mode: str,
    configured_provider_id: str,
    configured_model_id: str | None = None,
    required_role: str = "chat",
    required_capabilities: Collection[str] = (),
    availability: Availability = None,
    network_mode: str | None = None,
    privacy_profile: str | None = None,
) -> ModelInfo:
    """Select one model after eliminating every invalid candidate.

    Cost ranks already-valid models within a routing tier. Configured provider
    preference and input order are deterministic tie-breakers.
    """
    if routing_mode not in ROUTING_MODES:
        raise ProviderError(f"unknown routing mode {routing_mode!r}")

    required = tuple(dict.fromkeys(required_capabilities))
    permitted = [
        model
        for model in candidates
        if _permitted(model, network_mode, privacy_profile)
        and _available(model, availability)
        and supports(model, required_role)
        and all(bool(getattr(model, name, False)) for name in required)
    ]

    if routing_mode == "manual":
        selected = next(
            (
                model
                for model in permitted
                if model.provider_id == configured_provider_id
                and (
                    configured_model_id is None
                    or model.model_id == configured_model_id
                )
            ),
            None,
        )
    elif routing_mode == "local_only":
        selected = _best_candidate(
            [model for model in permitted if is_local_model(model)],
            configured_provider_id,
            required=frozenset(required),
            prefer_local=True,
            privacy_profile=privacy_profile or "",
        )
    elif routing_mode == "local_first":
        selected = _best_candidate(
            [model for model in permitted if is_local_model(model)],
            configured_provider_id,
            required=frozenset(required),
            prefer_local=True,
            privacy_profile=privacy_profile or "",
        )
        if selected is None:
            selected = _best_candidate(
                permitted,
                configured_provider_id,
                required=frozenset(required),
                prefer_local=False,
                privacy_profile=privacy_profile or "",
            )
    else:  # cloud_first
        clouds = [model for model in permitted if not is_local_model(model)]
        selected = _best_candidate(
            clouds,
            configured_provider_id,
            required=frozenset(required),
            prefer_local=False,
            privacy_profile=privacy_profile or "",
        )
        if selected is None:
            selected = _best_candidate(
                [model for model in permitted if is_local_model(model)],
                configured_provider_id,
                required=frozenset(required),
                prefer_local=True,
                privacy_profile=privacy_profile or "",
            )

    if selected is None:
        details = f"role {required_role!r}"
        if required:
            details += f" and capabilities {', '.join(required)}"
        if routing_mode == "local_only":
            details += " on an available local model"
        raise CapabilityError(
            f"no model satisfies {details} in routing mode {routing_mode!r}",
            provider_id=configured_provider_id,
            role=required_role,
            model_id=configured_model_id,
        )
    return selected


def _best_candidate(
    candidates: Sequence[ModelInfo],
    provider_id: str,
    *,
    required: frozenset[str],
    prefer_local: bool,
    privacy_profile: str,
) -> ModelInfo | None:
    if not candidates:
        return None
    return max(
        enumerate(candidates),
        key=lambda item: (
            score_model(
                item[1],
                required_capabilities=required,
                prefer_local=prefer_local,
                privacy_profile=privacy_profile,
                availability=True,
            ),
            item[1].provider_id == provider_id,
            -item[0],
        ),
    )[1]


def _permitted(
    model: ModelInfo, network_mode: str | None, privacy_profile: str | None
) -> bool:
    if network_mode in {"offline", "tools_only"} or privacy_profile in {
        "fully_local",
        "local_with_tools",
    }:
        return is_local_model(model)
    return True


def _available(model: ModelInfo, availability: Availability) -> bool:
    if availability is None:
        return True
    keys = (
        (model.provider_id, model.model_id),
        f"{model.provider_id}:{model.model_id}",
        model.model_id,
        model.provider_id,
    )
    return next((bool(availability[key]) for key in keys if key in availability), False)


__all__ = [
    "CLOUD_PROVIDER_IDS",
    "LOCAL_PROVIDER_IDS",
    "ROUTING_MODES",
    "is_local_model",
    "score_model",
    "select_model",
]
