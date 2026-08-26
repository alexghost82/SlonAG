import asyncio
import threading
import uuid
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
from config.settings import load_settings
from config.schema import Settings

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


def _get_settings() -> Settings:
    """Return settings with fallback to defaults. Never raises."""
    try:
        return load_settings()
    except Exception:  # pragma: no cover
        from config.schema import default_settings
        return default_settings()


def _resolve_model_info(provider_id: str, model_id: str = "") -> ModelInfo:
    """Build a ModelInfo from settings (or fall back to Gemini Live default)."""
    settings = _get_settings()
    selected_provider = getattr(settings, "provider_id", provider_id)
    selected_model_id = model_id or getattr(settings, "model_id", "")
    if selected_model_id:
        return ModelInfo(
            provider_id=selected_provider,
            model_id=selected_model_id,
            display_name=selected_model_id,
            text=True,
            streaming=True,
            tool_calling=True,
            source=selected_provider,
        )
    # Default: Gemini Live audio model for legacy compatibility.
    return LIVE_MODEL_INFO


def _get_api_key_for(provider_id: str) -> str | None:
    """Read the API key for a given provider, or None for local providers."""
    if provider_id == "local" or provider_id == "ollama" or provider_id == "llama_cpp":
        return None
    from config.secrets import get_secret
    return get_secret(f"{provider_id}_api_key")


def _build_stack():
    if build_runtime_stack is None:
        return None
    try:
        return build_runtime_stack(
            repo_root=BASE_DIR,
            provider_id=_get_settings().provider_id,
            network_mode=_get_settings().network_mode or "hybrid",
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
from sessions import ModelPolicy, TranscriptKind


class SlonLive:

    def __init__(
        self,
        ui: SlonUI,
        runtime_stack=None,
        selected_model: ModelInfo = LIVE_MODEL_INFO,
        session_id: str | None = None,
        workspace_id: str = "desktop",
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
        self.workspace_id = workspace_id
        session_manager = getattr(runtime_stack, "session_manager", None)
        if session_manager is not None:
            if session_id is None:
                logical_session = session_manager.create(
                    title="Live conversation",
                    agent_id="slon",
                    model_policy=ModelPolicy(
                        selected_model.provider_id, selected_model.model_id
                    ),
                    workspace_id=workspace_id,
                )
                session_id = logical_session.id
            else:
                logical_session = session_manager.get(
                    session_id, workspace_id=workspace_id
                )
                if (
                    logical_session.model_policy.provider_id,
                    logical_session.model_policy.model_id,
                ) != (selected_model.provider_id, selected_model.model_id):
                    raise ValueError("selected model does not match session model policy")
                logical_session = session_manager.resume(
                    session_id, workspace_id=workspace_id
                )
        self.session_id = session_id or str(uuid.uuid4())
        self.connection_generation = 0
        self._active_turn_id: str | None = None
        self._active_session_run = None
        self._active_user_persisted = False
        self._closed = False
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
        if self._closed or not self._loop or not self.session:
            return
        self.latency_trace.start_turn()
        self._active_turn_id = str(uuid.uuid4())
        manager = getattr(self.runtime_stack, "session_manager", None)
        if manager is not None:
            self._active_session_run = manager.start_run(
                self.session_id,
                workspace_id=self.workspace_id,
                effective_provider_id=self.selected_model.provider_id,
                effective_model_id=self.selected_model.model_id,
                turn_id=self._active_turn_id,
            )
            manager.append_event(
                self.session_id,
                workspace_id=self.workspace_id,
                turn_id=self._active_turn_id,
                kind=TranscriptKind.TEXT,
                role="user",
                text=text,
            )
            self._active_user_persisted = True
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
            self._emit_event(RuntimeEventKind.SPEAKING)
        elif not self.ui.muted:
            self._emit_event(RuntimeEventKind.LISTENING)

    def _emit_event(self, kind: RuntimeEventKind, **metadata):
        metadata.setdefault("session_id", self.session_id)
        metadata.setdefault("turn_id", self._active_turn_id)
        metadata.setdefault("connection_generation", self.connection_generation)
        return self.runtime_events.emit(kind, **metadata)

    def speak(self, text: str):
        if self._closed or not self._loop or not self.session:
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

    async def _persist_tool_call(self, fc) -> None:
        manager = getattr(self.runtime_stack, "session_manager", None)
        if manager is None or self._active_turn_id is None:
            return
        await asyncio.to_thread(
            manager.append_event,
            self.session_id,
            workspace_id=self.workspace_id,
            turn_id=self._active_turn_id,
            kind=TranscriptKind.TOOL_CALL,
            role="assistant",
            tool_call_id=fc.id,
            tool_name=fc.name,
            data=dict(fc.args or {}),
        )

    async def _persist_tool_result(self, fc, result, value) -> None:
        manager = getattr(self.runtime_stack, "session_manager", None)
        if manager is None or self._active_turn_id is None:
            return
        artifact_metadata = tuple(
            {
                "kind": item.kind,
                "path": item.path,
                "uri": item.uri,
                "mime_type": item.mime_type,
            }
            for item in result.artifacts
        )
        await asyncio.to_thread(
            manager.append_event,
            self.session_id,
            workspace_id=self.workspace_id,
            turn_id=self._active_turn_id,
            kind=TranscriptKind.TOOL_RESULT,
            role="tool",
            tool_call_id=fc.id,
            tool_name=fc.name,
            data={
                "result": value if result.ok else None,
                "error": None if result.ok else result.message or result.code,
            },
            artifacts=artifact_metadata,
        )

    async def _execute_tool(
        self, fc, *, persist: bool = True, result_sink: dict | None = None
    ) -> types.FunctionResponse:
        await self._start_live_turn()
        name = fc.name
        args = dict(fc.args or {})
        print(f"[SLON] 🔧 {name}")
        self._emit_event(
            RuntimeEventKind.TOOL_STARTED,
            tool_call_id=fc.id,
            tool_name=name,
        )
        self._emit_event(
            RuntimeEventKind.TOOL_PROGRESS,
            tool_call_id=fc.id,
            tool_name=name,
            progress=0.0,
        )
        self.latency_trace.mark("tool_execution_start")
        if persist:
            await self._persist_tool_call(fc)

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
            self._emit_event(RuntimeEventKind.LISTENING)
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
        if result_sink is not None:
            result_sink[fc.id] = (result, value if result.ok else None)
        if persist:
            try:
                await self._persist_tool_result(
                    fc, result, value if result.ok else None
                )
            except Exception as exc:
                # The handler may already have produced a side effect. Never
                # suppress its native response or invite a provider retry just
                # because durable recording failed afterward.
                self.ui.write_log(
                    f"ERR: durable tool result unavailable ({type(exc).__name__})"
                )
        self._emit_event(
            RuntimeEventKind.TOOL_FINISHED,
            tool_call_id=fc.id,
            tool_name=name,
            code=result.code,
        )
        self._emit_event(
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
            await self._start_live_turn()
            for call in calls:
                await self._persist_tool_call(call)
            captured = {}
            responses = list(await asyncio.gather(*(
                self._execute_tool(call, persist=False, result_sink=captured)
                for call in calls
            )))
            for call in calls:
                result, value = captured[call.id]
                try:
                    await self._persist_tool_result(call, result, value)
                except Exception as exc:
                    self.ui.write_log(
                        f"ERR: durable tool result unavailable ({type(exc).__name__})"
                    )
            return responses
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
            emit_event=self._emit_event,
            on_turn_started=self._start_live_turn,
            on_turn_finished=self._finish_live_turn,
        )

    async def _start_live_turn(self) -> None:
        if self._active_turn_id is not None:
            return
        self._active_turn_id = str(uuid.uuid4())
        self._active_user_persisted = False
        manager = getattr(self.runtime_stack, "session_manager", None)
        if manager is not None:
            self._active_session_run = await asyncio.to_thread(
                manager.start_run,
                self.session_id,
                workspace_id=self.workspace_id,
                effective_provider_id=self.selected_model.provider_id,
                effective_model_id=self.selected_model.model_id,
                turn_id=self._active_turn_id,
            )

    async def _finish_live_turn(
        self, user_text: str, assistant_text: str, interrupted: bool
    ) -> None:
        manager = getattr(self.runtime_stack, "session_manager", None)
        turn_id = self._active_turn_id
        run = self._active_session_run
        if manager is not None and turn_id is not None:
            from sessions import RunStatus, TranscriptKind, TranscriptState

            state = (
                TranscriptState.INTERRUPTED
                if interrupted else TranscriptState.COMPLETED
            )

            def persist() -> None:
                if user_text and not self._active_user_persisted:
                    manager.append_event(
                        self.session_id, workspace_id=self.workspace_id,
                        turn_id=turn_id, kind=TranscriptKind.TEXT,
                        state=state, role="user", text=user_text,
                    )
                if assistant_text:
                    manager.append_event(
                        self.session_id, workspace_id=self.workspace_id,
                        turn_id=turn_id, kind=TranscriptKind.TEXT,
                        state=state, role="assistant", text=assistant_text,
                    )
                if run is not None:
                    manager.finish_run(
                        run,
                        RunStatus.INTERRUPTED if interrupted else RunStatus.COMPLETED,
                    )

            await asyncio.to_thread(persist)
        self._active_turn_id = None
        self._active_session_run = None
        self._active_user_persisted = False

    async def _play_audio(self):
        await self.audio.play()

    def _on_connected(self, session, loop):
        self.connection_generation += 1
        self.session = session
        self._loop = loop
        self.audio.bind(session)
        self.audio_in_queue = self.audio.audio_in_queue
        self.out_queue = self.audio.out_queue

    def _on_disconnected(self):
        if self._active_session_run is not None:
            from sessions import RunStatus

            manager = getattr(self.runtime_stack, "session_manager", None)
            if manager is not None:
                manager.finish_run(self._active_session_run, RunStatus.INTERRUPTED)
        self._active_session_run = None
        self._active_turn_id = None
        self._active_user_persisted = False
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
        if self._closed:
            raise RuntimeError("logical session is closed")
        client = genai.Client(
            api_key=_get_api_key(),
            http_options={"api_version": "v1beta"},
        )
        task = asyncio.current_task()
        loop = asyncio.get_running_loop()
        manager = getattr(self.runtime_stack, "session_manager", None)

        def cancel() -> None:
            if task is not None:
                loop.call_soon_threadsafe(task.cancel)

        unregister = (
            manager.register_canceller(self.session_id, cancel)
            if manager is not None else lambda: None
        )
        try:
            await run_live_lifecycle(
                client=client,
                model_id=self.selected_model.model_id,
                build_config=self._build_config,
                on_connected=self._on_connected,
                on_disconnected=self._on_disconnected,
                tasks=self._session_tasks,
                ui=self.ui,
                emit_event=self._emit_event,
                should_stop=lambda: self._closed,
            )
        finally:
            unregister()

    async def close(self) -> None:
        """Idempotently stop the transport and close the logical session."""
        if self._closed:
            return
        self._closed = True
        session = self.session
        manager = getattr(self.runtime_stack, "session_manager", None)
        try:
            if session is not None:
                await session.close()
        finally:
            if manager is not None:
                await asyncio.to_thread(
                    manager.close, self.session_id, workspace_id=self.workspace_id
                )

JarvisLive = SlonLive


def _run_chat_agent(ui, settings, stack=None):
    """Run a provider-agnostic chat loop using AgentLoop + tool registry."""
    from mark.tools.builtin import build_builtin_registry
    from mark.tools.executor import ToolExecutor as SyncToolExecutor
    from mark.safety.policy import SafetyPolicy
    from agent.runtime import AgentLoop
    from providers.router import Router

    # Ensure all provider factories are registered
    from providers.openai import provider as _  # noqa: F401  # ensure registration
    from providers.gemini import provider as __  # noqa: F401  # ensure registration
    from providers.openrouter import provider as ___  # noqa: F401  # ensure registration
    from providers.local import ollama, llama_cpp  # noqa: F401  # ensure registration

    provider_id = getattr(settings, "provider_id", "gemini")
    model_id = getattr(settings, "model_id", "")

    # Audio-capable Gemini uses SlonLive, not AgentLoop.
    if provider_id == "gemini" and model_id and "audio" in model_id.lower():
        return False

    model_info = _resolve_model_info(provider_id, model_id)

    # Build key provider callback
    def key_provider(name: str) -> str | None:
        from config.secrets import get_secret
        return get_secret(name)

    # Build the router
    router = Router(
        provider_id=provider_id,
        network_mode=getattr(settings, "network_mode", None),
        privacy_profile=getattr(settings, "privacy_profile", None),
        routing_mode=getattr(settings, "routing_mode", None),
        key_provider=key_provider,
    )

    # Try to resolve the provider
    try:
        provider_instance = router._resolve(provider_id)
    except Exception as exc:  # pragma: no cover - needs api key
        ui.write_log(f"ERR: {exc}")
        print(f"[Main] provider init failed: {exc}")
        return True

    # Build tool registry and executor
    tool_registry = build_builtin_registry()
    safety = SafetyPolicy()
    tool_executor = SyncToolExecutor(tool_registry, safety)

    # Build and run the AgentLoop
    agent_loop = AgentLoop(
        model=model_info,
        provider=provider_instance,
        tool_executor=tool_executor,
    )

    async def _chat_loop():
        # Simple chat loop: prompt, get response, execute tools, loop.
        prompt = ""
        try:
            while not ui._closed:
                # Wait for text command from UI callback
                await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            pass

    print(f"[Main] Using provider={provider_id} model={model_id or model_info.model_id}")
    ui.write_log(f"SYS: provider={provider_id}")
    asyncio.create_task(_chat_loop())
    return True


def main():
    ui = SlonUI("face.png")

    def runner():
        ui.wait_for_api_key()
        settings = _get_settings()
        stack = getattr(ui, "_runtime_stack", None) or _build_stack()

        selected_provider = getattr(settings, "provider_id", "gemini")

        # Check if this is an audio-capable Gemini model → use SlonLive
        selected_model_id = getattr(settings, "model_id", "")
        is_gemini_audio = (
            selected_provider == "gemini"
            and selected_model_id
            and "audio" in selected_model_id.lower()
        )

        if is_gemini_audio:
            slon = SlonLive(ui, runtime_stack=stack)
            try:
                asyncio.run(slon.run())
            except KeyboardInterrupt:
                print("\nShutting down...")
        else:
            # Chat-based agent loop for non-Gemini or non-audio models
            _run_chat_agent(ui, settings, stack)
            print("\nChat agent finished.")

    threading.Thread(target=runner, daemon=True).start()
    ui.root.mainloop()


if __name__ == "__main__":
    main()
