"""Headless local-runtime process and catalog manager.

Chat HTTP stays in ``providers.local``. This module starts and stops an
injected runner, lists catalog entries, and refuses unconfirmed pulls.
A down runtime never falls back to a cloud provider.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Protocol, runtime_checkable

from providers.local import (
    DEFAULT_LLAMA_CPP_BASE_URL,
    DEFAULT_LOCAL_BASE_URL,
    DEFAULT_OLLAMA_BASE_URL,
)
from providers.local.endpoint import is_loopback_url

from acta.runtime.errors import (
    CODE_NOT_RUNNING,
    CODE_OK,
    CODE_OOM,
    CODE_PULL_UNCONFIRMED,
    CODE_REMOTE_URL,
    CODE_START_FAILED,
    CODE_STOP_FAILED,
    RuntimeManagerError,
    runtime_message_ru,
)

CLOUD_FALLBACK_ENABLED = False

PullHook = Callable[[str], None]


class RuntimeKind(StrEnum):
    OLLAMA = "ollama"
    LLAMA_CPP = "llama_cpp"
    OPENAI_COMPATIBLE = "openai_compatible"


DEFAULT_ENDPOINTS: dict[RuntimeKind, str] = {
    RuntimeKind.OLLAMA: DEFAULT_OLLAMA_BASE_URL,
    RuntimeKind.LLAMA_CPP: DEFAULT_LLAMA_CPP_BASE_URL,
    RuntimeKind.OPENAI_COMPATIBLE: DEFAULT_LOCAL_BASE_URL,
}


@dataclass(frozen=True)
class CatalogEntry:
    """One local model in the runtime catalog. No download happens here."""

    id: str
    size_bytes: int
    context: int
    capabilities: tuple[str, ...]
    ram_gb: float | None
    vram_gb: float | None
    source: str
    license: str
    status: str


@dataclass
class RuntimeMetrics:
    """Latency slots filled by the caller or an injected sampler."""

    ttft_ms: float | None = None
    tokens_per_sec: float | None = None


@dataclass(frozen=True)
class ProcessState:
    """Outcome of one injected runner call. Tests never spawn daemons."""

    running: bool
    code: str = CODE_OK


@dataclass(frozen=True)
class RuntimeStatus:
    """Health of the managed process. ``ok`` means the runtime is up."""

    kind: RuntimeKind
    running: bool
    ok: bool
    code: str
    endpoint: str
    message: str = ""


@runtime_checkable
class RuntimeRunner(Protocol):
    def start(self) -> ProcessState: ...

    def stop(self) -> ProcessState: ...

    def status(self) -> ProcessState: ...


def resolve_cloud_fallback(_status: RuntimeStatus) -> str | None:
    """Local runtime never substitutes a cloud provider when it is down."""
    return None


def default_endpoint(kind: RuntimeKind) -> str:
    return DEFAULT_ENDPOINTS[kind]


class RuntimeManager:
    """Start, stop, and inspect a local runtime through an injected runner."""

    def __init__(
        self,
        kind: RuntimeKind,
        runner: RuntimeRunner,
        *,
        endpoint: str | None = None,
        allow_remote: bool = False,
        pull: PullHook | None = None,
        catalog: Sequence[CatalogEntry] | None = None,
        metrics: RuntimeMetrics | None = None,
    ) -> None:
        self.kind = kind
        self.allow_remote = allow_remote
        self.endpoint = endpoint if endpoint is not None else default_endpoint(kind)
        self.metrics = metrics if metrics is not None else RuntimeMetrics()
        self._runner = runner
        self._pull = pull
        self._catalog: list[CatalogEntry] = list(catalog or ())
        self._assert_endpoint()

    def start(self) -> RuntimeStatus:
        self._assert_endpoint()
        return self._invoke(self._runner.start, failure_code=CODE_START_FAILED)

    def stop(self) -> RuntimeStatus:
        return self._invoke(self._runner.stop, failure_code=CODE_STOP_FAILED)

    def status(self) -> RuntimeStatus:
        return self._invoke(self._runner.status, failure_code=CODE_NOT_RUNNING)

    def list_catalog(self) -> list[CatalogEntry]:
        return list(self._catalog)

    def request_pull(
        self,
        model: str,
        *,
        confirm_size: bool,
        confirm_license: bool,
    ) -> None:
        if not confirm_size or not confirm_license:
            raise RuntimeManagerError(CODE_PULL_UNCONFIRMED)
        if self._pull is None:
            raise RuntimeManagerError(
                CODE_PULL_UNCONFIRMED,
                "pull hook is not configured",
            )
        self._pull(model)
        self._catalog = [
            replace(entry, status="installed") if entry.id == model else entry
            for entry in self._catalog
        ]

    def _assert_endpoint(self) -> None:
        if not isinstance(self.endpoint, str) or not self.endpoint.strip():
            raise RuntimeManagerError(CODE_REMOTE_URL)
        if self.allow_remote or is_loopback_url(self.endpoint):
            return
        raise RuntimeManagerError(CODE_REMOTE_URL)

    def _invoke(
        self,
        action: Callable[[], ProcessState],
        *,
        failure_code: str,
    ) -> RuntimeStatus:
        try:
            state = action()
        except MemoryError:
            return self._status(running=False, code=CODE_OOM)
        except Exception as exc:
            code = getattr(exc, "code", None)
            if code == CODE_OOM:
                return self._status(running=False, code=CODE_OOM)
            return self._status(running=False, code=failure_code)
        if state.code == CODE_OOM:
            return self._status(running=False, code=CODE_OOM)
        return self._status(running=state.running, code=state.code)

    def _status(self, *, running: bool, code: str) -> RuntimeStatus:
        healthy = running and code == CODE_OK
        return RuntimeStatus(
            kind=self.kind,
            running=running and code != CODE_OOM,
            ok=healthy,
            code=code,
            endpoint=self.endpoint,
            message=runtime_message_ru(code),
        )


__all__ = [
    "CLOUD_FALLBACK_ENABLED",
    "DEFAULT_ENDPOINTS",
    "CatalogEntry",
    "ProcessState",
    "PullHook",
    "RuntimeKind",
    "RuntimeManager",
    "RuntimeMetrics",
    "RuntimeRunner",
    "RuntimeStatus",
    "default_endpoint",
    "resolve_cloud_fallback",
]
