"""Unit tests for Desktop Control pairing service."""

from __future__ import annotations

import pytest

from server.pairing import (
    CODE_EXPIRED,
    CODE_INVALID,
    DeviceCredential,
    DeviceRecord,
    ExpiredPairingCodeError,
    InvalidPairingCodeError,
    PairingService,
    PairingStart,
    PendingChallenge,
)
from server.schemas import PairingCompleteResponse, PairingStartResponse


class FakeClock:
    def __init__(self, start: float = 1_700_000_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class ScriptedRng:
    """Deterministic rng for tests."""

    def __init__(
        self,
        codes: list[str] | None = None,
        device_ids: list[str] | None = None,
        secrets: list[str] | None = None,
    ) -> None:
        self._codes = list(codes or ["123456"])
        self._device_ids = list(device_ids or ["dev_test_1"])
        self._secrets = list(secrets or ["device-secret-once-ABC"])
        self._code_i = 0
        self._id_i = 0
        self._secret_i = 0

    def pairing_code(self) -> str:
        value = self._codes[min(self._code_i, len(self._codes) - 1)]
        self._code_i += 1
        return value

    def device_id(self) -> str:
        value = self._device_ids[min(self._id_i, len(self._device_ids) - 1)]
        self._id_i += 1
        return value

    def device_secret(self) -> str:
        value = self._secrets[min(self._secret_i, len(self._secrets) - 1)]
        self._secret_i += 1
        return value


def _service(
    *,
    clock: FakeClock | None = None,
    ttl: float = 60.0,
    rng: ScriptedRng | None = None,
    store: dict | None = None,
) -> tuple[PairingService, FakeClock, ScriptedRng]:
    clock = clock or FakeClock()
    rng = rng or ScriptedRng()
    service = PairingService(clock=clock, store=store, rng=rng, code_ttl_seconds=ttl)
    return service, clock, rng


def test_start_complete_happy_path_aligns_with_schemas() -> None:
    service, clock, rng = _service()
    started = service.start()
    assert isinstance(started, PairingStart)
    assert started.code == "123456"
    assert started.expires_at == clock.now + 60.0
    assert started.qr_payload == "mark-pair://local/123456"

    # Field names match PairingStartResponse / PairingCompleteResponse.
    assert PairingStartResponse.from_dict(
        {
            "code": started.code,
            "expires_at": started.expires_at,
            "qr_payload": started.qr_payload,
        }
    ) == PairingStartResponse(
        code=started.code,
        expires_at=started.expires_at,
        qr_payload=started.qr_payload,
    )

    cred = service.complete(started.code, "iPhone")
    assert isinstance(cred, DeviceCredential)
    assert cred.device_id == "dev_test_1"
    assert cred.device_secret == "device-secret-once-ABC"
    assert cred.expires_at is None
    assert service.is_active(cred.device_id) is True

    restored = PairingCompleteResponse.from_dict(
        {
            "device_id": cred.device_id,
            "device_secret": cred.device_secret,
            "expires_at": cred.expires_at,
        }
    )
    assert restored.device_id == cred.device_id
    assert restored.device_secret == cred.device_secret


def test_wrong_code_raises_typed_error() -> None:
    service, _, _ = _service()
    service.start()
    with pytest.raises(InvalidPairingCodeError) as exc_info:
        service.complete("000000", "Phone")
    assert exc_info.value.code == CODE_INVALID
    assert "device-secret" not in str(exc_info.value).lower()


def test_expired_code_raises_typed_error() -> None:
    service, clock, _ = _service(ttl=30.0)
    started = service.start()
    clock.advance(31.0)
    with pytest.raises(ExpiredPairingCodeError) as exc_info:
        service.complete(started.code, "Phone")
    assert exc_info.value.code == CODE_EXPIRED
    assert service.is_active("dev_test_1") is False


def test_code_is_one_time_only() -> None:
    service, _, _ = _service()
    started = service.start()
    service.complete(started.code, "Phone-A")
    with pytest.raises(InvalidPairingCodeError):
        service.complete(started.code, "Phone-B")


def test_revoke_blocks_is_active() -> None:
    service, _, _ = _service()
    started = service.start()
    cred = service.complete(started.code, "iPad")
    assert service.is_active(cred.device_id) is True
    service.revoke(cred.device_id)
    assert service.is_active(cred.device_id) is False
    # Idempotent revoke
    service.revoke(cred.device_id)
    assert service.is_active(cred.device_id) is False
    assert service.is_active("unknown_device") is False


def test_secret_not_in_repr_or_str_of_stored_records() -> None:
    secret = "super-secret-device-material-XYZ"
    service, _, _ = _service(rng=ScriptedRng(secrets=[secret]))
    started = service.start()
    cred = service.complete(started.code, "Watch")
    assert cred.device_secret == secret

    record = service.devices[cred.device_id]
    assert isinstance(record, DeviceRecord)
    assert secret not in repr(record)
    assert secret not in str(record)
    assert "secret_hash" not in repr(record)
    assert secret not in repr(service.devices)
    assert secret not in str(service.devices)

    # Pending challenges also never held the device secret.
    pending = PendingChallenge(code="999999", expires_at=1.0)
    assert secret not in repr(pending)
    assert secret not in str(pending)


def test_raw_secret_not_persisted_in_store() -> None:
    secret = "once-only-secret-value"
    store: dict = {}
    service, _, _ = _service(rng=ScriptedRng(secrets=[secret]), store=store)
    started = service.start()
    cred = service.complete(started.code, "Desktop")
    assert cred.device_secret == secret
    # Walk the entire injected store; raw secret must not appear.
    blob = repr(store)
    assert secret not in blob
    record = store["devices"][cred.device_id]
    assert record.secret_hash != secret
    assert secret not in record.secret_hash


def test_verify_device_secret_for_auth_hook() -> None:
    secret = "auth-hook-secret"
    service, _, _ = _service(rng=ScriptedRng(secrets=[secret]))
    started = service.start()
    cred = service.complete(started.code, "Phone")
    assert service.verify_device_secret(cred.device_id, secret) is True
    assert service.verify_device_secret(cred.device_id, "wrong") is False
    service.revoke(cred.device_id)
    assert service.verify_device_secret(cred.device_id, secret) is False


def test_injected_store_shared_across_instances() -> None:
    store: dict = {}
    clock = FakeClock()
    rng = ScriptedRng(
        codes=["111111", "222222"],
        device_ids=["dev_a", "dev_b"],
        secrets=["sec_a", "sec_b"],
    )
    a = PairingService(clock=clock, store=store, rng=rng, code_ttl_seconds=60.0)
    started = a.start()
    cred = a.complete(started.code, "A")
    b = PairingService(clock=clock, store=store, rng=rng, code_ttl_seconds=60.0)
    assert b.is_active(cred.device_id) is True
    b.revoke(cred.device_id)
    assert a.is_active(cred.device_id) is False
