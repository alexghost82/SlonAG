"""Connection and task lifecycle for Gemini Live."""

from __future__ import annotations

import asyncio
import traceback
from collections.abc import Awaitable, Callable
from typing import Any

from runtime.events import RuntimeEventKind


class _SessionTaskEnded(Exception):
    """Internal signal used to cancel sibling tasks when a session task ends."""


async def _run_owned_task(operation: Awaitable[None]) -> None:
    await operation
    raise _SessionTaskEnded


async def run_live_lifecycle(
    *,
    client: Any,
    model_id: str,
    build_config: Callable[[], Any],
    on_connected: Callable[[Any, asyncio.AbstractEventLoop], None],
    on_disconnected: Callable[[], None],
    tasks: Callable[[], tuple[Awaitable[None], ...]],
    ui: Any,
    emit_event: Callable[..., object] | None = None,
    reconnect_delay: float = 3.0,
    connect_timeout: float = 15.0,
    should_stop: Callable[[], bool] | None = None,
) -> None:
    """Reconnect forever while giving each connection fresh owned tasks."""
    while not (should_stop is not None and should_stop()):
        try:
            print("[SLON] 🔌 Connecting...")
            if emit_event is None:
                ui.set_state("THINKING")
            else:
                emit_event(RuntimeEventKind.THINKING)
            connection = client.aio.live.connect(model=model_id, config=build_config())
            session = await asyncio.wait_for(connection.__aenter__(), connect_timeout)
            try:
                on_connected(session, asyncio.get_running_loop())
                print("[SLON] ✅ Connected.")
                if emit_event is None:
                    ui.set_state("LISTENING")
                else:
                    emit_event(RuntimeEventKind.LISTENING)
                ui.write_log("SYS: Slon online.")
                try:
                    async with asyncio.TaskGroup() as task_group:
                        for operation in tasks():
                            task_group.create_task(_run_owned_task(operation))
                except* _SessionTaskEnded:
                    pass
            finally:
                await connection.__aexit__(None, None, None)
        except asyncio.CancelledError:
            on_disconnected()
            raise
        except Exception as exc:
            print(f"[SLON] ⚠️ {exc}")
            traceback.print_exc()
            on_disconnected()
        else:
            on_disconnected()

        if should_stop is not None and should_stop():
            return
        if emit_event is None:
            ui.set_state("THINKING")
        else:
            emit_event(RuntimeEventKind.THINKING)
        print(f"[SLON] 🔄 Reconnecting in {reconnect_delay:g}s...")
        await asyncio.sleep(reconnect_delay)


__all__ = ["run_live_lifecycle"]
