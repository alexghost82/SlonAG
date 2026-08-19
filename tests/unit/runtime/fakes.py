"""In-memory runtime runner for unit tests. Never starts a real process."""

from __future__ import annotations

from mark.runtime.errors import CODE_NOT_RUNNING, CODE_OK
from mark.runtime.manager import ProcessState


class FakeRunner:
    """Records start/stop/status and returns a configured process state."""

    def __init__(self, *, start_code: str = CODE_OK) -> None:
        self.start_code = start_code
        self.running = False
        self.start_calls = 0
        self.stop_calls = 0
        self.status_calls = 0

    def start(self) -> ProcessState:
        self.start_calls += 1
        if self.start_code != CODE_OK:
            self.running = False
            return ProcessState(running=False, code=self.start_code)
        self.running = True
        return ProcessState(running=True, code=CODE_OK)

    def stop(self) -> ProcessState:
        self.stop_calls += 1
        self.running = False
        return ProcessState(running=False, code=CODE_NOT_RUNNING)

    def status(self) -> ProcessState:
        self.status_calls += 1
        if self.running:
            return ProcessState(running=True, code=CODE_OK)
        return ProcessState(running=False, code=CODE_NOT_RUNNING)


class MemoryErrorRunner:
    """Raises ``MemoryError`` on start so the manager can map it to ``oom``."""

    def start(self) -> ProcessState:
        raise MemoryError("cannot allocate model weights")

    def stop(self) -> ProcessState:
        return ProcessState(running=False, code=CODE_NOT_RUNNING)

    def status(self) -> ProcessState:
        return ProcessState(running=False, code=CODE_NOT_RUNNING)
