"""Gemini Live response, transcription, and tool-response processing."""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any


async def receive_live_session(
    *,
    session: Any,
    audio_in_queue: Any,
    ui: Any,
    set_speaking: Callable[[bool], None],
    execute_tool: Callable[[Any], Any],
    update_memory: Callable[[str, str], None],
    latency_trace: Any,
) -> None:
    """Consume one Live session until it closes or raises."""
    print("[SLON] 👂 Recv started")
    output_transcript: list[str] = []
    input_transcript: list[str] = []
    awaiting_post_tool_response = False

    async for response in session.receive():
        provider_output = bool(
            response.data
            or response.tool_call
            or (
                response.server_content
                and response.server_content.output_transcription
                and response.server_content.output_transcription.text
            )
        )
        if provider_output:
            latency_trace.ensure_turn()
            latency_trace.mark("user_speech_end")
            latency_trace.mark("provider_first_response")
            if awaiting_post_tool_response:
                latency_trace.mark("provider_after_tool_first_response")
                awaiting_post_tool_response = False

        if response.data:
            audio_in_queue.put_nowait(response.data)

        if response.server_content:
            content = response.server_content
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

            if content.turn_complete:
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
            function_responses = []
            for function_call in response.tool_call.function_calls:
                print(f"[SLON] 📞 {function_call.name}")
                function_responses.append(await execute_tool(function_call))
            await session.send_tool_response(function_responses=function_responses)
            awaiting_post_tool_response = True


__all__ = ["receive_live_session"]
