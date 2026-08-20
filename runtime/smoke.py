"""Headless diagnostic entry point for the production Gemini Live path."""

from __future__ import annotations

import argparse
import asyncio
import os
import threading
import time
from dataclasses import dataclass

from main import SlonLive


class ConsoleControlPlane:
    def __init__(self, approval_mode: str) -> None:
        self.approval_mode = approval_mode
        self._text_handler = None

    def bind_text_handler(self, handler) -> None:
        self._text_handler = handler

    def update_state(self, **_state: object) -> None:
        return None

    def request_approval(
        self,
        tool_name: str,
        _arguments: object,
        *,
        source: str,
        reason: str,
    ) -> bool:
        del source
        if self.approval_mode == "deny":
            print(f"APPROVAL denied: {tool_name} ({reason})")
            return False
        answer = input(f"Approve {tool_name}? [y/N] ").strip().lower()
        return answer in {"y", "yes"}


@dataclass
class ConsoleUI:
    approval_mode: str
    muted: bool = False
    current_file: str | None = None

    def __post_init__(self) -> None:
        self.control_plane = ConsoleControlPlane(self.approval_mode)
        self.on_text_command = None
        self.connected = asyncio.Event()
        self.connection_count = 0

    def set_state(self, state: str) -> None:
        print(f"STATE {state}")

    def write_log(self, message: str) -> None:
        print(message)
        if message == "SYS: Slon online.":
            self.connection_count += 1
            self.connected.set()


def _resource_snapshot(live: SlonLive) -> dict[str, int | bool | None]:
    try:
        import psutil

        rss_bytes: int | None = psutil.Process(os.getpid()).memory_info().rss
    except (ImportError, OSError):
        rss_bytes = None
    audio_in = live.audio.audio_in_queue
    audio_out = live.audio.out_queue
    return {
        "monotonic_ms": round(time.monotonic() * 1000),
        "rss_bytes": rss_bytes,
        "threads": threading.active_count(),
        "asyncio_tasks": len(asyncio.all_tasks()),
        "audio_input_depth": audio_out.qsize() if audio_out is not None else 0,
        "audio_output_depth": audio_in.qsize() if audio_in is not None else 0,
        "active_session": live.session is not None,
    }


async def _wait_for_turn(live: SlonLive, previous_count: int, timeout: float) -> None:
    async with asyncio.timeout(timeout):
        while len(live.latency_trace.history()) <= previous_count:
            await asyncio.sleep(0.05)


async def _force_reconnect(live: SlonLive, ui: ConsoleUI, timeout: float) -> None:
    session = live.session
    if session is None:
        raise RuntimeError("cannot force reconnect without an active session")
    previous_count = ui.connection_count
    ui.connected.clear()
    await session.close()
    async with asyncio.timeout(timeout):
        while ui.connection_count <= previous_count:
            await asyncio.sleep(0.05)


async def run_smoke(args: argparse.Namespace) -> int:
    ui = ConsoleUI(args.approval)
    live = SlonLive(ui)
    live_task = asyncio.create_task(live.run(), name="gemini-live-smoke")
    snapshots: list[dict[str, int | bool | None]] = []
    try:
        await asyncio.wait_for(ui.connected.wait(), timeout=args.connect_timeout)
        snapshots.append(_resource_snapshot(live))
        for index, text in enumerate(args.text, start=1):
            previous_count = len(live.latency_trace.history())
            live._on_text_command(text)
            await _wait_for_turn(live, previous_count, args.turn_timeout)
            snapshots.append(_resource_snapshot(live))
            if args.force_reconnect_after_turn == index:
                await _force_reconnect(live, ui, args.connect_timeout)
                snapshots.append(_resource_snapshot(live))
        if not args.text:
            deadline = asyncio.get_running_loop().time() + args.duration
            while asyncio.get_running_loop().time() < deadline:
                await asyncio.sleep(min(args.snapshot_interval, max(
                    0.01, deadline - asyncio.get_running_loop().time()
                )))
                snapshots.append(_resource_snapshot(live))
    finally:
        live_task.cancel()
        try:
            await live_task
        except asyncio.CancelledError:
            pass

    print("LATENCY_STATISTICS", live.latency_trace.statistics())
    print("RESOURCE_SNAPSHOTS", snapshots)
    print(
        "AUDIO_DROPS",
        {
            "microphone": live.audio.dropped_microphone_chunks,
            "playback": live.audio.dropped_playback_chunks,
        },
    )
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--text", action="append", default=[])
    parser.add_argument("--duration", type=float, default=30.0)
    parser.add_argument("--turn-timeout", type=float, default=30.0)
    parser.add_argument("--connect-timeout", type=float, default=15.0)
    parser.add_argument("--snapshot-interval", type=float, default=60.0)
    parser.add_argument("--force-reconnect-after-turn", type=int, default=0)
    parser.add_argument(
        "--approval", choices=("deny", "prompt"), default="deny"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(run_smoke(_parser().parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
