"""Headless diagnostic entry point for the production Gemini Live path."""

from __future__ import annotations

import argparse
import asyncio
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

    def set_state(self, state: str) -> None:
        print(f"STATE {state}")

    def write_log(self, message: str) -> None:
        print(message)
        if message == "SYS: Slon online.":
            self.connected.set()


async def run_smoke(args: argparse.Namespace) -> int:
    ui = ConsoleUI(args.approval)
    live = SlonLive(ui)
    live_task = asyncio.create_task(live.run(), name="gemini-live-smoke")
    try:
        await asyncio.wait_for(ui.connected.wait(), timeout=args.connect_timeout)
        for text in args.text:
            live._on_text_command(text)
            await asyncio.sleep(args.turn_wait)
        if not args.text:
            await asyncio.sleep(args.duration)
    finally:
        live_task.cancel()
        try:
            await live_task
        except asyncio.CancelledError:
            pass

    print("LATENCY_STATISTICS", live.latency_trace.statistics())
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
    parser.add_argument("--turn-wait", type=float, default=10.0)
    parser.add_argument("--connect-timeout", type=float, default=15.0)
    parser.add_argument(
        "--approval", choices=("deny", "prompt"), default="deny"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(run_smoke(_parser().parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
