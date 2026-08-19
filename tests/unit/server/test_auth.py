"""Unit tests for per-device TokenService, authenticate, and RateLimiter."""

from __future__ import annotations

import pytest

from server.auth import (
    CODE_EXPIRED,
    CODE_INVALID_TOKEN,
    CODE_RATE_LIMITED,
    CODE_REPLAY,
    CODE_REVOKED,
    CODE_UNAUTHORIZED,
    AuthError,
    DeviceCredential,
    DevicePrincipal,
    RateLimiter,
    TokenService,
    authenticate,
)


class FakeClock:
    def __init__(self, start: float = 1_000_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _service(
    *,
    clock: FakeClock | None = None,
    revoked: set[str] | None = None,
    access_ttl: float = 60.0,
    refresh_ttl: float = 3600.0,
) -> tuple[TokenService, FakeClock]:
    clk = clock if clock is not None else FakeClock()
    svc = TokenService(
        signing_key=b"unit-test-signing-key",
        clock=clk,
        access_ttl_seconds=access_ttl,
        refresh_ttl_seconds=refresh_ttl,
        is_revoked=revoked if revoked is not None else set(),
    )
    return svc, clk


def _credential(device_id: str = "dev_1") -> DeviceCredential:
    return DeviceCredential(
        device_id=device_id,
        device_secret="device-secret-material-once",
        device_name="phone",
    )


def test_valid_token_authenticates() -> None:
    svc, _ = _service()
    issued = svc.mint(_credential())
    principal = authenticate(
        {"Authorization": f"Bearer {issued.access_token}"},
        token_service=svc,
    )
    assert isinstance(principal, DevicePrincipal)
    assert principal.device_id == "dev_1"
    assert principal.device_name == "phone"
    assert principal.jti == issued.jti


def test_authenticate_method_on_token_service() -> None:
    svc, _ = _service()
    issued = svc.mint(_credential())
    principal = svc.authenticate({"authorization": f"Bearer {issued.access_token}"})
    assert principal.device_id == "dev_1"


def test_expired_access_token_denied() -> None:
    svc, clock = _service(access_ttl=30.0)
    issued = svc.mint(_credential())
    clock.advance(31.0)
    with pytest.raises(AuthError) as exc_info:
        authenticate(
            {"Authorization": f"Bearer {issued.access_token}"},
            token_service=svc,
        )
    assert exc_info.value.code == CODE_EXPIRED


def test_forged_access_token_denied() -> None:
    svc, _ = _service()
    issued = svc.mint(_credential())
    suffix = "AAAA"
    if issued.access_token.endswith(suffix):
        suffix = "BBBB"
    forged = issued.access_token[:-4] + suffix
    with pytest.raises(AuthError) as exc_info:
        authenticate({"Authorization": f"Bearer {forged}"}, token_service=svc)
    assert exc_info.value.code in {CODE_INVALID_TOKEN, CODE_UNAUTHORIZED}


def test_wrong_signing_key_denied() -> None:
    clock = FakeClock()
    svc_a = TokenService(signing_key=b"key-a", clock=clock, access_ttl_seconds=60)
    svc_b = TokenService(signing_key=b"key-b", clock=clock, access_ttl_seconds=60)
    issued = svc_a.mint(_credential())
    with pytest.raises(AuthError) as exc_info:
        svc_b.authenticate({"Authorization": f"Bearer {issued.access_token}"})
    assert exc_info.value.code == CODE_INVALID_TOKEN


def test_revoked_device_always_denied() -> None:
    revoked: set[str] = set()
    svc, _ = _service(revoked=revoked)
    issued = svc.mint(_credential())
    revoked.add("dev_1")
    with pytest.raises(AuthError) as exc_info:
        authenticate(
            {"Authorization": f"Bearer {issued.access_token}"},
            token_service=svc,
        )
    assert exc_info.value.code == CODE_REVOKED

    with pytest.raises(AuthError) as mint_exc:
        svc.mint(_credential())
    assert mint_exc.value.code == CODE_REVOKED


def test_revocation_callback() -> None:
    revoked_ids = {"dev_gone"}

    def is_revoked(device_id: str) -> bool:
        return device_id in revoked_ids

    svc = TokenService(
        signing_key=b"unit-test-signing-key",
        clock=FakeClock(),
        is_revoked=is_revoked,
    )
    with pytest.raises(AuthError) as exc_info:
        svc.mint(_credential("dev_gone"))
    assert exc_info.value.code == CODE_REVOKED


def test_refresh_rotates_and_old_refresh_fails() -> None:
    svc, _ = _service()
    first = svc.mint(_credential())
    second = svc.refresh(first.refresh_token)
    assert second.access_token != first.access_token
    assert second.refresh_token != first.refresh_token
    assert second.device_id == "dev_1"

    with pytest.raises(AuthError) as exc_info:
        svc.refresh(first.refresh_token)
    assert exc_info.value.code == CODE_INVALID_TOKEN

    principal = svc.authenticate({"Authorization": f"Bearer {second.access_token}"})
    assert principal.device_id == "dev_1"


def test_refresh_rejects_revoked_device() -> None:
    revoked: set[str] = set()
    svc, _ = _service(revoked=revoked)
    issued = svc.mint(_credential())
    revoked.add("dev_1")
    with pytest.raises(AuthError) as exc_info:
        svc.refresh(issued.refresh_token)
    assert exc_info.value.code == CODE_REVOKED


def test_replayed_nonce_rejected() -> None:
    svc, _ = _service()
    svc.mint(_credential(), nonce="n-1")
    with pytest.raises(AuthError) as exc_info:
        svc.mint(_credential("dev_2"), nonce="n-1")
    assert exc_info.value.code == CODE_REPLAY


def test_replayed_jti_rejected_when_provided() -> None:
    svc, _ = _service()
    svc.mint(_credential(), jti="jti-fixed-1")
    with pytest.raises(AuthError) as exc_info:
        svc.mint(_credential("dev_2"), jti="jti-fixed-1")
    assert exc_info.value.code == CODE_REPLAY


def test_consume_jti_on_verify_blocks_replay() -> None:
    svc, _ = _service()
    issued = svc.mint(_credential())
    first = svc.verify_access(issued.access_token, consume_jti=True)
    assert first.device_id == "dev_1"
    with pytest.raises(AuthError) as exc_info:
        svc.verify_access(issued.access_token, consume_jti=True)
    assert exc_info.value.code == CODE_REPLAY


def test_missing_authorization_denied() -> None:
    svc, _ = _service()
    with pytest.raises(AuthError) as exc_info:
        authenticate({}, token_service=svc)
    assert exc_info.value.code == CODE_UNAUTHORIZED


def test_rate_limiter_trips() -> None:
    clock = FakeClock()
    limiter = RateLimiter(capacity=2, refill_per_second=0.0, clock=clock)
    assert limiter.allow("dev_1") is True
    assert limiter.allow("dev_1") is True
    assert limiter.allow("dev_1") is False
    with pytest.raises(AuthError) as exc_info:
        limiter.check("dev_1")
    assert exc_info.value.code == CODE_RATE_LIMITED


def test_rate_limiter_refills_with_clock() -> None:
    clock = FakeClock()
    limiter = RateLimiter(capacity=1, refill_per_second=1.0, clock=clock)
    assert limiter.allow("k") is True
    assert limiter.allow("k") is False
    clock.advance(1.0)
    assert limiter.allow("k") is True


def test_no_secrets_in_error_strings() -> None:
    svc, _ = _service()
    secret = "rt_super_secret_refresh_value_abc123"
    with pytest.raises(AuthError) as exc_info:
        svc.refresh(secret)
    text = str(exc_info.value)
    assert secret not in text
    assert "rt_super_secret" not in text
    assert "api_key" not in text.lower() or "[REDACTED]" in text

    leaky = AuthError(
        "failed api_key=sk-abcdefghijklmnop Bearer tokensecret",
        code=CODE_UNAUTHORIZED,
    )
    assert "sk-abcdefghijklmnop" not in str(leaky)
    assert "tokensecret" not in str(leaky)
    assert "[REDACTED]" in str(leaky)


def test_issued_tokens_repr_hides_secrets() -> None:
    svc, _ = _service()
    issued = svc.mint(_credential())
    text = repr(issued)
    assert issued.access_token not in text
    assert issued.refresh_token not in text
    assert "device-secret-material-once" not in text
    assert "refresh_token='***'" in text

    cred_text = repr(_credential())
    assert "device-secret-material-once" not in cred_text
    assert "***" in cred_text


def test_public_dict_has_no_api_keys() -> None:
    svc, _ = _service()
    issued = svc.mint(_credential())
    public = issued.to_public_dict()
    blob = str(public).lower()
    assert "api_key" not in blob
    assert "gemini" not in blob
    assert "openrouter" not in blob
    assert public["device_id"] == "dev_1"
    assert "access_token" in public
    assert "refresh_token" in public
