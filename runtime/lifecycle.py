"""Connection and task lifecycle for Gemini Live."""

from __future__ import annotations

import asyncio
import traceback
from collections.abc import Awaitable, Callable
from typing import Any


async def run_live_lifecycle(
    *,
    client: Any,
    model_id: str,
    build_config: Callable[[], Any],
    on_connected: Callable[[Any, asyncio.AbstractEventLoop], None],
    on_disconnected: Callable[[], None],
    tasks: Callable[[], tuple[Awaitable[None], ...]],
    ui: Any,
    reconnect_delay: float = 3.0,
) -> None:
    """Reconnect forever while giving each connection fresh owned tasks."""
    while True:
        try:
            print("[SLON] 🔌 Connecting...")
            ui.set_state("THINKING")
            async with client.aio.live.connect(
                model=model_id, config=build_config()
            ) as session:
                on_connected(session, asyncio.get_running_loop())
                print("[SLON] ✅ Connected.")
                ui.set_state("LISTENING")
                ui.write_log("SYS: Slon online.")
                async with asyncio.TaskGroup() as task_group:
                    for operation in tasks():
                        task_group.create_task(operation)
        except asyncio.CancelledError:
            on_disconnected()
            raise
        except Exception as exc:
            print(f"[SLON] ⚠️ {exc}")
            traceback.print_exc()
            on_disconnected()
        else:
            on_disconnected()

        ui.set_state("THINKING")
        print(f"[SLON] 🔄 Reconnecting in {reconnect_delay:g}s...")
        await asyncio.sleep(reconnect_delay)


__all__ = ["run_live_lifecycle"]
