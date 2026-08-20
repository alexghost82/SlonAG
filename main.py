import asyncio
import threading
import sys
import traceback
from pathlib import Path

import sounddevice as sd
from google import genai
from google.genai import types
from ui import SlonUI, JarvisUI
from memory.memory_manager import (
    load_memory, update_memory, format_memory_for_prompt,
    should_extract_memory, extract_memory
)

# New-stack bridge (Wave 13); optional — never break legacy Gemini Live.
try:
    from mark.bridge import authorize_tool, build_runtime_stack
except Exception:  # pragma: no cover
    authorize_tool = None  # type: ignore[assignment]
    build_runtime_stack = None  # type: ignore[assignment]


def get_base_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


BASE_DIR        = get_base_dir()
PROMPT_PATH     = BASE_DIR / "core" / "prompt.txt"
LIVE_MODEL          = "models/gemini-2.5-flash-native-audio-preview-12-2025"
CHANNELS            = 1
SEND_SAMPLE_RATE    = 16000
RECEIVE_SAMPLE_RATE = 24000
CHUNK_SIZE          = 1024


def _get_api_key() -> str:
    from config.secrets import get_secret

    key = get_secret("gemini_api_key")
    if key is None:
        raise RuntimeError("Gemini API key is not configured.")
    return key


def _key_provider(name: str) -> str | None:
    """Injected secret reader for the runtime bridge (no values logged)."""
    from config.secrets import get_secret

    return get_secret(name)


def _build_stack():
    if build_runtime_stack is None:
        return None
    try:
        return build_runtime_stack(
            repo_root=BASE_DIR,
            provider_id="gemini",
            network_mode="hybrid",
            key_provider=_key_provider,
        )
    except Exception as exc:
        print(f"[Bridge] unavailable: {exc}")
        return None


def _load_system_prompt() -> str:
    try:
        return PROMPT_PATH.read_text(encoding="utf-8")
    except Exception:
        return (
            "You are Slon, a sharp and efficient AI assistant. "
            "Be concise, direct, and always use the provided tools to complete tasks. "
            "Never simulate or guess results — always call the appropriate tool."
        )
    
_last_memory_input = ""

def _update_memory_async(user_text: str, slon_text: str = "", jarvis_text: str = "") -> None:
    global _last_memory_input

    assistant_text = (slon_text or jarvis_text or "").strip()

    if len(user_text) < 5 or user_text == _last_memory_input:
        return
    _last_memory_input = user_text

    try:
        api_key = _get_api_key()
        if not should_extract_memory(user_text, assistant_text, api_key):
            return
        data = extract_memory(user_text, assistant_text, api_key)
        if data:
            update_memory(data)
            print(f"[Memory] ✅ {list(data.keys())}")
    except Exception as e:
        if "429" not in str(e):
            print(f"[Memory] ⚠️ {e}")

from dataclasses import replace

from mark.safety import SafetyPolicy, UntrustedSource
from mark.tools import ToolExecutor, ToolRegistry
from mark.tools.builtin import build_builtin_registry
from mark.tools.exporters.gemini import export_gemini_tools
from mark.tools.legacy.adapters import with_legacy_context
from agent.latency import LatencyTrace


def _contextual_registry(*, ui, speak) -> ToolRegistry:
    registry = ToolRegistry()
    for spec in build_builtin_registry().list():
        registry.register(
            replace(
                spec,
                handler=with_legacy_context(spec.handler, speak=speak, player=ui),
            )
        )
    return registry


TOOL_DECLARATIONS = export_gemini_tools(build_builtin_registry().list())


class SlonLive:

    def __init__(self, ui: SlonUI, runtime_stack=None):
        self.ui             = ui
        self.session        = None
        self.audio_in_queue = None
        self.out_queue      = None
        self._loop          = None
        self._is_speaking   = False
        self._speaking_lock = threading.Lock()
        self.runtime_stack  = runtime_stack
        self.tool_registry = _contextual_registry(ui=ui, speak=self.speak)
        self.tool_executor = ToolExecutor(
            self.tool_registry, SafetyPolicy(), confirmer=lambda _decision: True
        )
        self.latency_trace = LatencyTrace()
        self.ui.on_text_command = self._on_text_command
        control_plane = getattr(self.ui, "control_plane", None)
        if control_plane is not None:
            control_plane.bind_text_handler(self._on_text_command)
            control_plane.update_state(model_id=LIVE_MODEL)
        if runtime_stack is not None:
            for line in runtime_stack.summary_lines():
                try:
                    self.ui.write_log(f"SYS: bridge {line}")
                except Exception:
                    print(f"[Bridge] {line}")

    def _on_text_command(self, text: str):
        if not self._loop or not self.session:
            return
        asyncio.run_coroutine_threadsafe(
            self.session.send_client_content(
                turns={"parts": [{"text": text}]},
                turn_complete=True
            ),
            self._loop
        )

    def set_speaking(self, value: bool):
        with self._speaking_lock:
            self._is_speaking = value
        if value:
            self.ui.set_state("SPEAKING")
        elif not self.ui.muted:
            self.ui.set_state("LISTENING")

    def speak(self, text: str):
        if not self._loop or not self.session:
            return
        asyncio.run_coroutine_threadsafe(
            self.session.send_client_content(
                turns={"parts": [{"text": text}]},
                turn_complete=True
            ),
            self._loop
        )

    def speak_error(self, tool_name: str, error: str):
        short = str(error)[:120]
        self.ui.write_log(f"ERR: {tool_name} — {short}")
        self.speak(f"Sir, {tool_name} encountered an error. {short}")

    def _build_config(self) -> types.LiveConnectConfig:
        from datetime import datetime

        memory     = load_memory()
        mem_str    = format_memory_for_prompt(memory)
        sys_prompt = _load_system_prompt()

        now      = datetime.now()
        time_str = now.strftime("%A, %B %d, %Y — %I:%M %p")
        time_ctx = (
            f"[CURRENT DATE & TIME]\n"
            f"Right now it is: {time_str}\n"
            f"Use this to calculate exact times for reminders.\n\n"
        )

        parts = [time_ctx]
        if mem_str:
            parts.append(mem_str)
        parts.append(sys_prompt)

        return types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            output_audio_transcription={},
            input_audio_transcription={},
            system_instruction="\n".join(parts),
            tools=[{"function_declarations": TOOL_DECLARATIONS}],
            session_resumption=types.SessionResumptionConfig(),
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name="Charon"
                    )
                )
            ),
        )

    async def _execute_tool(self, fc) -> types.FunctionResponse:
        name = fc.name
        args = dict(fc.args or {})
        print(f"[SLON] 🔧 {name}  {args}")
        self.ui.set_state("THINKING")
        self.latency_trace.mark("tool_execution_start")

        if name == "file_processor" and not args.get("file_path") and self.ui.current_file:
            args["file_path"] = self.ui.current_file

        if authorize_tool is not None and self.runtime_stack is not None:
            allowed, reason = authorize_tool(
                self.runtime_stack, name, args, source="desktop_ui"
            )
            if not allowed and "confirm" in reason.lower():
                control_plane = getattr(self.ui, "control_plane", None)
                if control_plane is not None:
                    allowed = await asyncio.to_thread(
                        control_plane.request_approval,
                        name,
                        args,
                        source="desktop_ui",
                        reason=reason,
                    )
            if not allowed:
                result = {"error": f"Blocked by SafetyPolicy: {reason}"}
                return types.FunctionResponse(id=fc.id, name=name, response=result)

        result = await asyncio.to_thread(
            self.tool_executor.execute,
            name,
            args,
            source=UntrustedSource.USER,
            intent="Gemini Live function call",
        )
        self.latency_trace.mark("tool_execution_finish")
        if not self.ui.muted:
            self.ui.set_state("LISTENING")
        if result.ok:
            value = result.data if result.data is not None else result.message or "Done."
            response = {"result": value}
        else:
            response = {"error": result.message, "code": result.code}
            self.speak_error(name, result.message or result.code)
        print(f"[SLON] 📤 {name} → {str(response)[:80]}")
        self.latency_trace.mark("observation_returned")
        return types.FunctionResponse(id=fc.id, name=name, response=response)

    async def _send_realtime(self):
        while True:
            msg = await self.out_queue.get()
            await self.session.send_realtime_input(media=msg)

    async def _listen_audio(self):
        print("[SLON] 🎤 Mic started")
        loop = asyncio.get_event_loop()

        def callback(indata, frames, time_info, status):
            with self._speaking_lock:
                slon_speaking = self._is_speaking
            if not slon_speaking and not self.ui.muted:
                data = indata.tobytes()
                loop.call_soon_threadsafe(
                    self.out_queue.put_nowait,
                    {"data": data, "mime_type": "audio/pcm"}
                )

        try:
            with sd.InputStream(
                samplerate=SEND_SAMPLE_RATE,
                channels=CHANNELS,
                dtype="int16",
                blocksize=CHUNK_SIZE,
                callback=callback,
            ):
                print("[SLON] 🎤 Mic stream open")
                while True:
                    await asyncio.sleep(0.1)
        except Exception as e:
            print(f"[SLON] ❌ Mic: {e}")
            raise

    async def _receive_audio(self):
        print("[SLON] 👂 Recv started")
        out_buf, in_buf = [], []

        try:
            while True:
                async for response in self.session.receive():

                    if response.data:
                        self.audio_in_queue.put_nowait(response.data)

                    if response.server_content:
                        sc = response.server_content

                        if sc.output_transcription and sc.output_transcription.text:
                            self.set_speaking(True)
                            txt = sc.output_transcription.text.strip()
                            if txt:
                                out_buf.append(txt)

                        if sc.input_transcription and sc.input_transcription.text:
                            txt = sc.input_transcription.text.strip()
                            if txt:
                                in_buf.append(txt)

                        if sc.turn_complete:
                            self.latency_trace.mark("user_speech_end")
                            self.latency_trace.mark("turn_complete")
                            self.set_speaking(False)

                            full_in = " ".join(in_buf).strip()
                            if full_in:
                                self.ui.write_log(f"You: {full_in}")
                            in_buf = []

                            full_out = " ".join(out_buf).strip()
                            if full_out:
                                self.ui.write_log(f"Slon: {full_out}")
                            out_buf = []

                            if full_in and len(full_in) > 5:
                                threading.Thread(
                                    target=_update_memory_async,
                                    args=(full_in, full_out),
                                    daemon=True
                                ).start()

                    if response.tool_call:
                        self.latency_trace.mark("tool_call_received")
                        fn_responses = []
                        for fc in response.tool_call.function_calls:
                            print(f"[SLON] 📞 {fc.name}")
                            fr = await self._execute_tool(fc)
                            fn_responses.append(fr)
                        await self.session.send_tool_response(
                            function_responses=fn_responses
                        )

        except Exception as e:
            print(f"[SLON] ❌ Recv: {e}")
            traceback.print_exc()
            raise

    async def _play_audio(self):
        print("[SLON] 🔊 Play started")
        loop = asyncio.get_event_loop()

        stream = sd.RawOutputStream(
            samplerate=RECEIVE_SAMPLE_RATE,
            channels=CHANNELS,
            dtype="int16",
            blocksize=CHUNK_SIZE,
        )
        stream.start()
        try:
            while True:
                chunk = await self.audio_in_queue.get()
                self.latency_trace.mark("first_audio_output")
                self.set_speaking(True)
                await asyncio.to_thread(stream.write, chunk)
        except Exception as e:
            print(f"[SLON] ❌ Play: {e}")
            raise
        finally:
            self.set_speaking(False)
            stream.stop()
            stream.close()

    async def run(self):
        client = genai.Client(
            api_key=_get_api_key(),
            http_options={"api_version": "v1beta"}
        )

        while True:
            try:
                print("[SLON] 🔌 Connecting...")
                self.ui.set_state("THINKING")
                config = self._build_config()

                async with (
                    client.aio.live.connect(model=LIVE_MODEL, config=config) as session,
                    asyncio.TaskGroup() as tg,
                ):
                    self.session        = session
                    self._loop          = asyncio.get_event_loop()
                    self.audio_in_queue = asyncio.Queue()
                    self.out_queue      = asyncio.Queue(maxsize=10)

                    print("[SLON] ✅ Connected.")
                    self.ui.set_state("LISTENING")
                    self.ui.write_log("SYS: Slon online.")

                    tg.create_task(self._send_realtime())
                    tg.create_task(self._listen_audio())
                    tg.create_task(self._receive_audio())
                    tg.create_task(self._play_audio())
                    
            except Exception as e:
                print(f"[SLON] ⚠️ {e}")
                traceback.print_exc()

            self.set_speaking(False)
            self.ui.set_state("THINKING")
            print("[SLON] 🔄 Reconnecting in 3s...")
            await asyncio.sleep(3)

JarvisLive = SlonLive


def main():
    ui = SlonUI("face.png")

    def runner():
        ui.wait_for_api_key()
        # Live Gemini path remains the default when Gemini keys are present.
        stack = _build_stack()
        slon = SlonLive(ui, runtime_stack=stack)
        try:
            asyncio.run(slon.run())
        except KeyboardInterrupt:
            print("\nShutting down...")

    threading.Thread(target=runner, daemon=True).start()
    ui.root.mainloop()


if __name__ == "__main__":
    main()
