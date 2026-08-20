"""Gemini Live response, transcription, and tool-response processing."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable
from typing import Any

from runtime.events import RuntimeEventKind


async def receive_live_session(
    *,
    session: Any,
    audio_in_queue: Any,
    enqueue_playback: Callable[[bytes], None] | None = None,
    interrupt_playback: Callable[[], int] | None = None,
    ui: Any,
    set_speaking: Callable[[bool], None],
    execute_tool: Callable[[Any], Any],
    execute_tools: Callable[[list[Any]], Any] | None = None,
    update_memory: Callable[[str, str], None],
    latency_trace: Any,
    emit_event: Callable[..., object] | None = None,
    operation_timeout: float = 30.0,
) -> None:
    """Consume one Live session until it closes or raises."""
    print("[SLON] 👂 Recv started")
    output_transcript: list[str] = []
    input_transcript: list[str] = []
    awaiting_post_tool_response = False
    accept_playback = True

    if enqueue_playback is None:
        enqueue_playback = audio_in_queue.put_nowait
    if interrupt_playback is None:
        def interrupt_playback() -> int:
            cleared = 0
            while True:
                try:
                    audio_in_queue.get_nowait()
                except asyncio.QueueEmpty:
                    return cleared
                cleared += 1

    async for response in session.receive():
        content = response.server_content
        interrupted = bool(content and getattr(content, "interrupted", False))
        if interrupted:
            accept_playback = False
            invalidated = interrupt_playback()
            ui.write_log(f"SYS: playback interrupted cleared={invalidated}")
            output_transcript.clear()
            cancel_turn = getattr(latency_trace, "cancel_turn", None)
            if cancel_turn is not None:
                cancel_turn()
            if emit_event is not None:
                emit_event(RuntimeEventKind.CANCELLED)

        voice_activity = getattr(response, "voice_activity", None)
        activity_type = str(getattr(voice_activity, "voice_activity_type", ""))
        if activity_type.endswith("ACTIVITY_START"):
            latency_trace.mark("user_input_activity_start")
        elif activity_type.endswith("ACTIVITY_END"):
            latency_trace.mark("user_input_activity_end")

        # Transcription is the first unambiguous evidence that a later server
        # message belongs to the new turn rather than the interrupted response.
        if content and not interrupted:
            input_text = getattr(
                getattr(content, "input_transcription", None), "text", ""
            )
            output_text = getattr(
                getattr(content, "output_transcription", None), "text", ""
            )
            if input_text or output_text:
                accept_playback = True

        provider_output = bool(
            (response.data and accept_playback and not interrupted)
            or response.tool_call
            or (
                response.server_content
                and response.server_content.output_transcription
                and response.server_content.output_transcription.text
            )
        )
        if provider_output:
            latency_trace.ensure_turn()
            latency_trace.mark("provider_first_response")
            if awaiting_post_tool_response:
                latency_trace.mark("provider_after_tool_first_response")
                awaiting_post_tool_response = False

        if response.data and accept_playback and not interrupted:
            enqueue_playback(response.data)

        if content and not interrupted:
            if content.output_transcription and content.output_transcription.text:
                set_speaking(True)
                text = content.output_transcription.text.strip()
                if text:
                    output_transcript.append(text)

            if content.input_transcription and content.input_transcription.text:
                if not latency_trace.active:
                    latency_trace.start_turn()
                text = content.input_transcription.text.strip()
                if text:
                    input_transcript.append(text)

            if content.turn_complete and not interrupted:
                breakdown = latency_trace.finish_turn()
                set_speaking(False)
                user_text = " ".join(input_transcript).strip()
                assistant_text = " ".join(output_transcript).strip()
                input_transcript.clear()
                output_transcript.clear()
                if user_text:
                    ui.write_log(f"You: {user_text}")
                if assistant_text:
                    ui.write_log(f"Slon: {assistant_text}")
                if breakdown:
                    rendered = " ".join(
                        f"{name}={value:.1f}ms"
                        for name, value in breakdown.items()
                    )
                    ui.write_log(f"SYS: latency {rendered}")
                if len(user_text) > 5:
                    threading.Thread(
                        target=update_memory,
                        args=(user_text, assistant_text),
                        daemon=True,
                    ).start()

        if response.tool_call:
            latency_trace.mark("tool_call_received")
            function_calls = list(response.tool_call.function_calls)
            for function_call in function_calls:
                print(f"[SLON] 📞 {function_call.name}")
            if execute_tools is not None:
                function_responses = list(await execute_tools(function_calls))
            else:
                function_responses = []
                for function_call in function_calls:
                    function_responses.append(await execute_tool(function_call))
            await asyncio.wait_for(
                session.send_tool_response(function_responses=function_responses),
                timeout=operation_timeout,
            )
            awaiting_post_tool_response = True


__all__ = ["receive_live_session"]
