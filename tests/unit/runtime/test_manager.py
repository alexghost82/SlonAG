from __future__ import annotations

import pytest

from acta.runtime import (
    CLOUD_FALLBACK_ENABLED,
    CODE_NOT_RUNNING,
    CODE_OK,
    CODE_OOM,
    CODE_PULL_UNCONFIRMED,
    CODE_REMOTE_URL,
    CatalogEntry,
    RuntimeKind,
    RuntimeManager,
    RuntimeManagerError,
    RuntimeMetrics,
    default_endpoint,
    resolve_cloud_fallback,
    runtime_message_ru,
)
from providers.local.endpoint import is_loopback_url

from tests.unit.runtime.fakes import FakeRunner, MemoryErrorRunner


def _entry(model_id: str = "local-compact") -> CatalogEntry:
    return CatalogEntry(
        id=model_id,
        size_bytes=1_000_000_000,
        context=4096,
        capabilities=("text", "streaming"),
        ram_gb=8.0,
        vram_gb=None,
        source="local",
        license="Apache-2.0",
        status="available",
    )


def test_start_stop_status_with_fake_runner() -> None:
    runner = FakeRunner()
    manager = RuntimeManager(RuntimeKind.OLLAMA, runner)

    idle = manager.status()
    assert idle.running is False
    assert idle.ok is False
    assert idle.code == CODE_NOT_RUNNING
    assert runner.status_calls == 1
    assert is_loopback_url(idle.endpoint)

    started = manager.start()
    assert started.ok is True
    assert started.running is True
    assert started.code == CODE_OK
    assert started.kind is RuntimeKind.OLLAMA
    assert runner.start_calls == 1
    assert manager.status().running is True

    stopped = manager.stop()
    assert stopped.running is False
    assert stopped.code == CODE_NOT_RUNNING
    assert runner.stop_calls == 1
    assert manager.status().running is False


@pytest.mark.parametrize("kind", list(RuntimeKind))
def test_default_endpoints_are_loopback(kind: RuntimeKind) -> None:
    endpoint = default_endpoint(kind)
    assert is_loopback_url(endpoint)
    manager = RuntimeManager(kind, FakeRunner())
    assert manager.endpoint == endpoint
    assert is_loopback_url(manager.endpoint)


def test_remote_url_rejected() -> None:
    runner = FakeRunner()
    with pytest.raises(RuntimeManagerError) as exc_info:
        RuntimeManager(
            RuntimeKind.OPENAI_COMPATIBLE,
            runner,
            endpoint="http://example.com/v1",
        )
    assert exc_info.value.code == CODE_REMOTE_URL
    assert runner.start_calls == 0


@pytest.mark.parametrize(
    "url",
    (
        "http://example.com",
        "https://example.com/v1",
        "http://8.8.8.8:8080",
        "http://192.168.1.10",
    ),
)
def test_non_loopback_urls_rejected_when_remote_disallowed(url: str) -> None:
    with pytest.raises(RuntimeManagerError) as exc_info:
        RuntimeManager(RuntimeKind.LLAMA_CPP, FakeRunner(), endpoint=url)
    assert exc_info.value.code == CODE_REMOTE_URL


def test_allow_remote_permits_example_com() -> None:
    runner = FakeRunner()
    manager = RuntimeManager(
        RuntimeKind.OLLAMA,
        runner,
        endpoint="http://example.com",
        allow_remote=True,
    )
    started = manager.start()
    assert started.ok is True
    assert started.endpoint == "http://example.com"
    assert runner.start_calls == 1


@pytest.mark.parametrize(
    ("confirm_size", "confirm_license"),
    (
        (False, False),
        (True, False),
        (False, True),
    ),
)
def test_pull_without_confirms_raises(
    confirm_size: bool, confirm_license: bool
) -> None:
    calls: list[str] = []
    manager = RuntimeManager(RuntimeKind.OLLAMA, FakeRunner(), pull=calls.append)
    with pytest.raises(RuntimeManagerError) as exc_info:
        manager.request_pull(
            "local-compact",
            confirm_size=confirm_size,
            confirm_license=confirm_license,
        )
    assert exc_info.value.code == CODE_PULL_UNCONFIRMED
    assert calls == []


def test_pull_with_confirms_calls_hook_once() -> None:
    calls: list[str] = []
    manager = RuntimeManager(
        RuntimeKind.OLLAMA,
        FakeRunner(),
        pull=calls.append,
        catalog=(_entry(),),
    )
    manager.request_pull("local-compact", confirm_size=True, confirm_license=True)
    assert calls == ["local-compact"]
    installed = manager.list_catalog()
    assert len(installed) == 1
    assert installed[0].id == "local-compact"
    assert installed[0].status == "installed"


def test_catalog_entry_exposes_required_fields() -> None:
    entry = _entry()
    assert entry.id == "local-compact"
    assert entry.size_bytes == 1_000_000_000
    assert entry.context == 4096
    assert entry.capabilities == ("text", "streaming")
    assert entry.ram_gb == 8.0
    assert entry.vram_gb is None
    assert entry.source == "local"
    assert entry.license == "Apache-2.0"
    assert entry.status == "available"


def test_oom_result_code_does_not_raise_uncaught() -> None:
    manager = RuntimeManager(RuntimeKind.LLAMA_CPP, FakeRunner(start_code=CODE_OOM))
    result = manager.start()
    assert result.ok is False
    assert result.running is False
    assert result.code == CODE_OOM
    assert result.message == runtime_message_ru(CODE_OOM)
    # The Russian message "не хватает памяти..." contains "памяти" (memory)
    msg = result.message.lower()
    assert "memory" in msg or "памят" in msg or "local" in msg or "llama" in msg, f"OOM message wrong: {result.message}"
    assert resolve_cloud_fallback(result) is None
    assert CLOUD_FALLBACK_ENABLED is False


def test_oom_memory_error_does_not_raise_uncaught() -> None:
    manager = RuntimeManager(RuntimeKind.OLLAMA, MemoryErrorRunner())
    result = manager.start()
    assert result.code == CODE_OOM
    assert result.ok is False
    assert result.running is False
    assert resolve_cloud_fallback(result) is None


def test_metrics_slots_start_unset_and_accept_sampler_values() -> None:
    manager = RuntimeManager(RuntimeKind.OPENAI_COMPATIBLE, FakeRunner())
    assert manager.metrics.ttft_ms is None
    assert manager.metrics.tokens_per_sec is None
    manager.metrics = RuntimeMetrics(ttft_ms=120.0, tokens_per_sec=35.5)
    assert manager.metrics.ttft_ms == 120.0
    assert manager.metrics.tokens_per_sec == 35.5
