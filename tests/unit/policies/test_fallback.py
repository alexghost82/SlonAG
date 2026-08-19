from __future__ import annotations

import inspect

import pytest

from policies.fallback import (
    POLICY_NAMES,
    CostOrSpeedFallbackPolicy,
    LocalOnlyFallbackPolicy,
    NeverFallbackPolicy,
    PreselectedCloudFallbackPolicy,
    SameProviderFallbackPolicy,
    create_policy,
    resolve_policy,
)
from providers.errors import ProviderError
from providers.router import CLOUD_PROVIDER_IDS, FallbackPolicy

ERROR = ProviderError("unit-test failure")


def test_named_policies_satisfy_router_protocol() -> None:
    policies = (
        NeverFallbackPolicy(),
        SameProviderFallbackPolicy(),
        LocalOnlyFallbackPolicy(),
        PreselectedCloudFallbackPolicy("openai"),
        CostOrSpeedFallbackPolicy(target_provider_id="local"),
    )
    for policy in policies:
        assert isinstance(policy, FallbackPolicy)
        assert callable(policy.next)


@pytest.mark.parametrize("name", sorted(POLICY_NAMES))
def test_create_policy_builds_each_named_policy(name: str) -> None:
    kwargs: dict[str, object] = {}
    if name == "preselected_cloud":
        kwargs["cloud_provider_id"] = "gemini"
    if name == "cost_or_speed":
        kwargs["target_provider_id"] = "local"
    policy = create_policy(name, **kwargs)
    assert isinstance(policy, FallbackPolicy)
    assert policy.name == name


def test_never_returns_none_for_local_and_cloud() -> None:
    policy = NeverFallbackPolicy()
    assert policy.next("local", ERROR) is None
    assert policy.next("ollama", ERROR) is None
    for cloud_id in CLOUD_PROVIDER_IDS:
        assert policy.next(cloud_id, ERROR) is None


@pytest.mark.parametrize("cloud_id", sorted(CLOUD_PROVIDER_IDS))
@pytest.mark.parametrize(
    "constraint",
    [{"network_mode": "offline"}, {"privacy_profile": "fully_local"}],
)
def test_never_and_offline_equivalent_never_return_cloud_id(
    cloud_id: str, constraint: dict[str, str]
) -> None:
    never = NeverFallbackPolicy()
    offline = resolve_policy(
        "preselected_cloud", cloud_provider_id=cloud_id, **constraint
    )
    assert never.next("local", ERROR) is None
    assert offline.next("local", ERROR) is None
    assert never.next(cloud_id, ERROR) is None
    assert offline.next(cloud_id, ERROR) is None
    assert not is_cloud_id(never.next("local", ERROR))
    assert not is_cloud_id(offline.next("local", ERROR))


def test_same_provider_without_alternate_returns_none() -> None:
    policy = SameProviderFallbackPolicy()
    assert policy.next("openai", ERROR) is None
    assert policy.next("local", ERROR) is None


def test_same_provider_does_not_invent_a_hidden_model_list() -> None:
    source = inspect.getsource(SameProviderFallbackPolicy)
    assert "TEXT_MODELS" not in source
    assert "gpt-" not in source
    policy = SameProviderFallbackPolicy()
    assert not hasattr(policy, "models")
    assert policy.next("gemini", ERROR) is None
    assert SameProviderFallbackPolicy(alternate_provider_id="openai").next(
        "gemini", ERROR
    ) is None
    assert SameProviderFallbackPolicy(alternate_provider_id="openai").next(
        "openai", ERROR
    ) is None


@pytest.mark.parametrize("cloud_id", sorted(CLOUD_PROVIDER_IDS))
def test_local_only_never_returns_cloud_id(cloud_id: str) -> None:
    policy = LocalOnlyFallbackPolicy()
    assert policy.next(cloud_id, ERROR) == "local"
    assert policy.next(cloud_id, ERROR) not in CLOUD_PROVIDER_IDS
    assert policy.next("local", ERROR) is None
    assert policy.next("ollama", ERROR) == "local"
    assert policy.next("unknown-runtime", ERROR) == "local"
    assert policy.next("local", ERROR) != cloud_id


def test_local_only_rejects_cloud_target() -> None:
    with pytest.raises(ProviderError, match="cloud provider"):
        LocalOnlyFallbackPolicy("gemini")


def test_preselected_cloud_returns_configured_id_from_local() -> None:
    policy = PreselectedCloudFallbackPolicy("openai")
    assert policy.requires_confirmation is True
    assert policy.next("local", ERROR) == "openai"
    assert policy.next("gemini", ERROR) == "openai"
    assert policy.next("openai", ERROR) is None


def test_preselected_cloud_rejects_non_cloud_target() -> None:
    with pytest.raises(ProviderError, match="known cloud"):
        PreselectedCloudFallbackPolicy("local")


def test_cost_or_speed_without_target_returns_none() -> None:
    policy = CostOrSpeedFallbackPolicy()
    assert policy.next("local", ERROR) is None
    assert policy.next("openai", ERROR) is None


def test_cost_or_speed_local_to_cloud_requires_explicit_permission() -> None:
    blocked = CostOrSpeedFallbackPolicy(target_provider_id="openai")
    assert blocked.allow_local_to_cloud is False
    assert blocked.next("local", ERROR) is None
    no_confirm = CostOrSpeedFallbackPolicy(
        target_provider_id="openai",
        allow_local_to_cloud=True,
        requires_confirmation=False,
    )
    assert no_confirm.next("local", ERROR) is None
    allowed = CostOrSpeedFallbackPolicy(
        target_provider_id="openai",
        prefer="speed",
        allow_local_to_cloud=True,
        requires_confirmation=True,
    )
    assert allowed.requires_confirmation is True
    assert allowed.next("local", ERROR) == "openai"
    assert allowed.next("openai", ERROR) is None


def test_cost_or_speed_cloud_to_local_does_not_need_cloud_permission() -> None:
    policy = CostOrSpeedFallbackPolicy(target_provider_id="local", prefer="cost")
    assert policy.next("gemini", ERROR) == "local"
    assert policy.requires_confirmation is True


def test_create_policy_rejects_unknown_name() -> None:
    with pytest.raises(ProviderError, match="unknown fallback policy"):
        create_policy("silent-default")


def test_resolve_policy_rejects_unknown_settings_enums() -> None:
    with pytest.raises(ProviderError, match="network_mode"):
        resolve_policy("never", network_mode="airplane")
    with pytest.raises(ProviderError, match="privacy_profile"):
        resolve_policy("never", privacy_profile="public")


def is_cloud_id(provider_id: str | None) -> bool:
    return provider_id in CLOUD_PROVIDER_IDS
