import asyncio
import threading
import sys
from pathlib import Path

from google import genai
from google.genai import types
from providers.contracts import ModelInfo
from ui import SlonUI, JarvisUI
from memory.memory_manager import (
    load_memory, update_memory, format_memory_for_prompt,
    should_extract_memory, extract_memory
)

# New-stack bridge (Wave 13); optional — never break legacy Gemini Live.
try:
    from mark.bridge import build_runtime_stack
except Exception:  # pragma: no cover
    build_runtime_stack = None  # type: ignore[assignment]


def get_base_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


BASE_DIR        = get_base_dir()
PROMPT_PATH     = BASE_DIR / "core" / "prompt.txt"
LIVE_MODEL_INFO = ModelInfo(
    provider_id="gemini",
    model_id="models/gemini-2.5-flash-native-audio-preview-12-2025",
    display_name="Gemini 2.5 Flash Native Audio Preview",
    text=True,
    streaming=True,
    tool_calling=True,
    audio_input=True,
    audio_output=True,
    source="Google",
    license="Proprietary",
)
LIVE_MODEL = LIVE_MODEL_INFO.model_id  # compatibility alias


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
        print(f"[Bridge] unavailable: {type(exc).__name__}")
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
    except Exception as exc:
        if "429" not in str(exc):
            print(f"[Memory] ⚠️ {type(exc).__name__}")

from mark.tools.exporters.gemini import export_gemini_tools
from agent.latency import TurnLatencyTracker
from runtime.audio import AudioPipeline
from runtime.lifecycle import run_live_lifecycle
from runtime.live_session import receive_live_session
from runtime.tool_bridge import LiveToolBridge, build_live_registry
from runtime.events import RuntimeEventBus, RuntimeEventKind, UIRuntimeEventSink


class SlonLive:

    def __init__(
        self,
        ui: SlonUI,
        runtime_stack=None,
        selected_model: ModelInfo = LIVE_MODEL_INFO,
    ):
        self.ui             = ui
        self.session        = None
        self.audio_in_queue = None
        self.out_queue      = None
        self._loop          = None
        self._is_speaking   = False
        self._speaking_lock = threading.Lock()
        self.runtime_stack  = runtime_stack
        if selected_model.provider_id != "gemini" or not (
            selected_model.audio_input and selected_model.audio_output
        ):
            raise ValueError("Gemini Live requires an audio-capable Gemini ModelInfo")
        self.selected_model = selected_model
        base_registry = getattr(runtime_stack, "tool_registry", None)
        policy = getattr(runtime_stack, "safety", None)
        live_registry = build_live_registry(
            ui=ui,
            speak=self.speak,
            base_registry=base_registry,
        )
        self.tool_bridge = LiveToolBridge(
            ui=ui,
            speak=self.speak,
            registry=live_registry,
            policy=policy,
        )
        self.tool_registry = self.tool_bridge.registry
        self.tool_executor = self.tool_bridge.executor
        self.tool_declarations = export_gemini_tools(self.tool_registry.list())
        self.latency_trace = TurnLatencyTracker()
        self.runtime_events = RuntimeEventBus()
        self.runtime_events.subscribe(UIRuntimeEventSink(ui))
        self.audio = AudioPipeline(
            ui=ui,
            set_speaking=self.set_speaking,
            latency_trace=self.latency_trace,
            speaking_lock=self._speaking_lock,
            is_speaking=lambda: self._is_speaking,
        )
        self.ui.on_text_command = self._on_text_command
        control_plane = getattr(self.ui, "control_plane", None)
        if control_plane is not None:
            control_plane.bind_text_handler(self._on_text_command)
            control_plane.update_state(model_id=self.selected_model.model_id)
        if runtime_stack is not None:
            for line in runtime_stack.summary_lines():
                try:
                    self.ui.write_log(f"SYS: bridge {line}")
                except Exception:
                    print(f"[Bridge] {line}")

    def _on_text_command(self, text: str):
        if not self._loop or not self.session:
            return
        self.latency_trace.start_turn()
        self.latency_trace.mark("user_speech_end")
        self.latency_trace.mark("provider_request_start")
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
            self.runtime_events.emit(RuntimeEventKind.SPEAKING)
        elif not self.ui.muted:
            self.runtime_events.emit(RuntimeEventKind.LISTENING)

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
            realtime_input_config=types.RealtimeInputConfig(
                activity_handling=types.ActivityHandling.START_OF_ACTIVITY_INTERRUPTS
            ),
            system_instruction="\n".join(parts),
            tools=[{"function_declarations": self.tool_declarations}],
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
        print(f"[SLON] 🔧 {name}")
        self.runtime_events.emit(
            RuntimeEventKind.TOOL_STARTED,
            tool_call_id=fc.id,
            tool_name=name,
        )
        self.runtime_events.emit(
            RuntimeEventKind.TOOL_PROGRESS,
            tool_call_id=fc.id,
            tool_name=name,
            progress=0.0,
        )
        self.latency_trace.mark("tool_execution_start")

        result = await self.tool_bridge.execute(
            name,
            args,
            intent="Gemini Live function call",
            call_id=fc.id,
        )
        self.latency_trace.mark_at("approval_start", result.approval_started_at)
        self.latency_trace.mark_at("approval_finish", result.approval_finished_at)
        self.latency_trace.mark_at("tool_handler_start", result.handler_started_at)
        self.latency_trace.mark("tool_execution_finish")
        if not self.ui.muted:
            self.runtime_events.emit(RuntimeEventKind.LISTENING)
        if result.ok:
            value = result.data if result.data is not None else result.message or "Done."
            response = {"result": value}
        else:
            response = {"error": result.message, "code": result.code}
            self.ui.write_log(
                f"ERR: {name} — {str(result.message or result.code)[:120]}"
            )
        print(f"[SLON] 📤 {name} → {'ok' if result.ok else result.code}")
        self.latency_trace.mark("observation_returned")
        self.runtime_events.emit(
            RuntimeEventKind.TOOL_FINISHED,
            tool_call_id=fc.id,
            tool_name=name,
            code=result.code,
        )
        self.runtime_events.emit(
            RuntimeEventKind.TOOL_PROGRESS,
            tool_call_id=fc.id,
            tool_name=name,
            progress=1.0,
            code=result.code,
        )
        return types.FunctionResponse(id=fc.id, name=name, response=response)

    async def _execute_tools(self, calls) -> list[types.FunctionResponse]:
        """Run only an explicitly safe, independent Live batch concurrently."""
        specs = []
        identities = []
        for call in calls:
            try:
                spec = self.tool_registry.get(call.name)
            except Exception:
                spec = None
            specs.append(spec)
            identities.append((call.name, repr(sorted(dict(call.args or {}).items()))))
        safe = all(
            spec is not None
            and spec.parallel_safe
            and spec.read_only
            and spec.idempotent
            and not spec.side_effects
            for spec in specs
        )
        independent = len(set(identities)) == len(identities)
        if safe and independent:
            return list(await asyncio.gather(*(self._execute_tool(call) for call in calls)))
        results = []
        for call in calls:
            results.append(await self._execute_tool(call))
        return results

    async def _send_realtime(self):
        await self.audio.send_realtime()

    async def _listen_audio(self):
        await self.audio.listen()

    async def _receive_audio(self):
        if self.session is None or self.audio.audio_in_queue is None:
            raise RuntimeError("live session is not connected")
        await receive_live_session(
            session=self.session,
            audio_in_queue=self.audio.audio_in_queue,
            enqueue_playback=self.audio.enqueue_playback,
            interrupt_playback=self.audio.interrupt_playback,
            ui=self.ui,
            set_speaking=self.set_speaking,
            execute_tool=self._execute_tool,
            execute_tools=self._execute_tools,
            update_memory=_update_memory_async,
            latency_trace=self.latency_trace,
            emit_event=self.runtime_events.emit,
        )

    async def _play_audio(self):
        await self.audio.play()

    def _on_connected(self, session, loop):
        self.session = session
        self._loop = loop
        self.audio.bind(session)
        self.audio_in_queue = self.audio.audio_in_queue
        self.out_queue = self.audio.out_queue

    def _on_disconnected(self):
        self.set_speaking(False)
        self.session = None
        self._loop = None
        self.audio.unbind()
        self.audio_in_queue = None
        self.out_queue = None

    def _session_tasks(self):
        return (
            self._send_realtime(),
            self._listen_audio(),
            self._receive_audio(),
            self._play_audio(),
        )

    async def run(self):
        client = genai.Client(
            api_key=_get_api_key(),
            http_options={"api_version": "v1beta"},
        )
        await run_live_lifecycle(
            client=client,
            model_id=self.selected_model.model_id,
            build_config=self._build_config,
            on_connected=self._on_connected,
            on_disconnected=self._on_disconnected,
            tasks=self._session_tasks,
            ui=self.ui,
            emit_event=self.runtime_events.emit,
        )

JarvisLive = SlonLive


def main():
    ui = SlonUI("face.png")

    def runner():
        ui.wait_for_api_key()
        # Live Gemini path remains the default when Gemini keys are present.
        stack = getattr(ui, "_runtime_stack", None) or _build_stack()
        slon = SlonLive(ui, runtime_stack=stack)
        try:
            asyncio.run(slon.run())
        except KeyboardInterrupt:
            print("\nShutting down...")

    threading.Thread(target=runner, daemon=True).start()
    ui.root.mainloop()


if __name__ == "__main__":
    main()
