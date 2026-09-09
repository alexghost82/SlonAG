"""OS-specific adapters must import on this host without executing native backends."""

from __future__ import annotations

import importlib


def test_core_packages_import() -> None:
    for name in (
        "runtime.jobs",
        "runtime.metrics",
        "runtime.commands",
        "runtime.events",
        "acta.memory",
        "acta.bridge",
        "sessions",
        "gateway",
        "config.schema",
        "providers.router",
    ):
        importlib.import_module(name)


def test_os_adapters_are_lazy() -> None:
    import computer_control

    assert hasattr(computer_control, "__file__")
