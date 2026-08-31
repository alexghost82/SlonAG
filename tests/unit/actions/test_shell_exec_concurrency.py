"""Concurrent-access tests for shell_exec internals.

Validates that :data:`actions.shell_exec._active_procs` and its associated
lock handle concurrent add / remove / iterate / cleanup without races.
"""

from __future__ import annotations

import subprocess
import threading
import time
from typing import Any

import pytest


def test_active_procs_add_remove_serial() -> None:
    """Sequential add → discard is always consistent."""
    from actions.shell_exec import _active_procs, _active_lock

    _active_procs.clear()

    proc1 = subprocess.Popen(["true"])
    proc2 = subprocess.Popen(["true"])

    with _active_lock:
        _active_procs.add(proc1)
        _active_procs.add(proc2)
        assert _active_procs == {proc1, proc2}

    with _active_lock:
        _active_procs.discard(proc1)
        assert _active_procs == {proc2}
        _active_procs.discard(proc2)
        assert _active_procs == set()

    proc1.wait()
    proc2.wait()


def test_active_procs_concurrent_add_remove() -> None:
    """Multiple threads adding and removing must not raise."""
    from actions.shell_exec import _active_procs, _active_lock

    _active_procs.clear()
    errors: list[Exception] = []
    barrier = threading.Barrier(10)

    def add_then_remove(idx: int) -> None:
        try:
            barrier.wait(timeout=5)
            proc = subprocess.Popen(["sleep", "0.05"])
            with _active_lock:
                _active_procs.add(proc)
                # Iterate while holding lock — should never raise
                snapshot = set(_active_procs)
                assert proc in snapshot

            time.sleep(0.02)

            with _active_lock:
                _active_procs.discard(proc)
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=add_then_remove, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert not errors, f"Concurrent access raised: {errors}"
    assert _active_procs == set()


def test_active_procs_concurrent_iterate_while_modify() -> None:
    """Iterating a copy of _active_procs must not race with concurrent add/discard."""
    from actions.shell_exec import _active_procs, _active_lock

    _active_procs.clear()
    errors: list[Exception] = []
    stop_event = threading.Event()
    procs: list[subprocess.Popen[Any]] = []

    def modifier() -> None:
        while not stop_event.is_set():
            proc = subprocess.Popen(["sleep", "0.01"])
            with _active_lock:
                _active_procs.add(proc)
            procs.append(proc)
            time.sleep(0.005)
            with _active_lock:
                _active_procs.discard(proc)
            proc.wait()

    def iterator() -> None:
        while not stop_event.is_set():
            try:
                with _active_lock:
                    snapshot = set(_active_procs)
                # Use the snapshot (safe copy)
                for p in snapshot:
                    _ = p.poll()  # noqa: B018
            except Exception as exc:
                errors.append(exc)

    mod_thread = threading.Thread(target=modifier)
    iter_threads = [threading.Thread(target=iterator) for _ in range(5)]

    for t in iter_threads:
        t.start()
    mod_thread.start()

    time.sleep(0.3)
    stop_event.set()
    mod_thread.join(timeout=5)
    for t in iter_threads:
        t.join(timeout=5)

    assert not errors, f"Race detected: {errors}"


def test_kill_tree_thread_safe() -> None:
    """_kill_tree must work correctly when called concurrently."""
    from actions.shell_exec import _kill_tree

    proc = subprocess.Popen(["sleep", "10"])

    errors: list[Exception] = []
    barrier = threading.Barrier(5)

    def kill_once() -> None:
        try:
            barrier.wait(timeout=5)
            _kill_tree(proc)
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=kill_once) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    assert not errors, f"Concurrent kill_tree raised: {errors}"
    proc.kill()
    proc.wait()


def test_shell_exec_logging_configured_via_get_logger() -> None:
    """Module uses logging.getLogger(__name__), not basicConfig."""
    import logging

    from actions import shell_exec

    assert isinstance(shell_exec.logger, logging.Logger)
    assert shell_exec.logger.name == "actions.shell_exec"


def test_or_client_logging_configured_via_get_logger() -> None:
    """or_client module uses logging.getLogger(__name__), not basicConfig."""
    import logging

    import or_client

    assert isinstance(or_client.logger, logging.Logger)
    assert or_client.logger.name == "or_client"


def test_no_basicconfig_in_library_modules() -> None:
    """Library modules must not call logging.basicConfig()."""
    import ast
    from pathlib import Path

    package_root = Path(__file__).resolve().parents[3]

    library_modules = [
        "or_client.py",
        "actions/shell_exec.py",
    ]

    for module_name in library_modules:
        mod_path = package_root / module_name
        text = mod_path.read_text(encoding="utf-8")
        tree = ast.parse(text)

        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if (
                    isinstance(node.func, ast.Attribute)
                    and node.func.attr == "basicConfig"
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "logging"
                ):
                    pytest.fail(
                        f"{module_name} calls logging.basicConfig() — "
                        "library modules must not configure root logging"
                    )
