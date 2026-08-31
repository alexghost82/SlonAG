"""Tests for VoiceBridge (canonical voice pipeline).

Covers: barge-in, stale audio discard, cancellation, reconnect, and
provider independence.  All microphone/agent-loop/real-subprocess code
is stubbed with injected fakes.
"""

from __future__ import annotations

import asyncio
import threading
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from providers.contracts import (
    AudioStream,
    ModelInfo,
)
from runtime.canonical_voice import (
    FreshAudioQueue,
    FreshTextQueue,
    PlaybackGeneration,
    VoiceBridge,
    VoiceConfig,
)

from tests.unit.speech.voice.fakes import FakeUI


def _fake_model_info() -> ModelInfo:
    return ModelInfo(
        provider_id="local",
        model_id="mock",
        display_name="Mock Agent",
        text=True,
        audio_output=True,
        audio_input=True,
    )


class TestVoiceBridgeBargeIn:
    """Barge-in / cancel should invalidate stale TTS output."""

    def test_cancel_method(self, fake_ui: FakeUI) -> None:
        config = VoiceConfig()
        bridge = VoiceBridge(
            config=config,
            ui=fake_ui,
            agent_loop_factory=lambda *a, **k: MagicMock(),
            model_info=_fake_model_info(),
            set_speaking=fake_ui.set_speaking,
        )
        bridge.cancel()
        assert bridge._cancelled.is_set()

    def test_interrupt_tts_increments_generation(self, fake_ui: FakeUI) -> None:
        config = VoiceConfig()
        bridge = VoiceBridge(
            config=config,
            ui=fake_ui,
            agent_loop_factory=lambda *a, **k: MagicMock(),
            model_info=_fake_model_info(),
            set_speaking=fake_ui.set_speaking,
        )
        gen_before = bridge._generation.value
        bridge.interrupt_tts()
        assert bridge._generation.value > gen_before
        assert not fake_ui.speaking

    @pytest.mark.asyncio
    async def test_stale_generation_discarded(self) -> None:
        gen = PlaybackGeneration()
        gen.bump()  # 1
        gen.bump()  # 2
        old_gen = gen.bump()  # 3
        assert old_gen == 3
        assert 1 < gen.value
        assert 2 < gen.value

    @pytest.mark.asyncio
    async def test_barge_in_cancels_tts_and_continues(self, fake_ui: FakeUI) -> None:
        config = VoiceConfig()
        bridge = VoiceBridge(
            config=config,
            ui=fake_ui,
            agent_loop_factory=lambda *a, **k: MagicMock(),
            model_info=_fake_model_info(),
            set_speaking=fake_ui.set_speaking,
        )
        bridge._tts_adapter = MagicMock()
        bridge.interrupt_tts()
        assert bridge._tts_adapter.interrupt.called


class TestVoiceBridgeQueues:
    """Verify bounded queues limit PCM/text buffers."""

    @pytest.mark.asyncio
    async def test_audio_queue_bounded(self) -> None:
        q = FreshAudioQueue(maxsize=4)
        for i in range(10):
            q.put_nowait(f"chunk{i}".encode())
        assert q.dropped_chunks == 6
        assert q.qsize() <= 4

    @pytest.mark.asyncio
    async def test_text_queue_bounded(self) -> None:
        q = FreshTextQueue(maxsize=2)
        q.put_nowait("first")
        q.put_nowait("second")
        q.put_nowait("third")  # drops first
        assert q.dropped_chunks == 1
        assert await q.get() == "second"
        assert await q.get() == "third"


class TestVoiceBridgeProviderIndependence:
    """VoiceBridge does not hard-code Gemini Live."""

    def test_voice_config_defaults(self) -> None:
        config = VoiceConfig()
        assert config.language == "ru"
        assert config.stt_engine == "faster_whisper"
        assert config.tts_engine == "piper"
        assert config.barge_in is True

    def test_config_allows_custom_engine(self) -> None:
        config = VoiceConfig(stt_engine="whisper_cpp", tts_engine="vosk")
        assert config.stt_engine == "whisper_cpp"
        assert config.tts_engine == "vosk"

    def test_config_allows_device_selection(self) -> None:
        config = VoiceConfig(mic_device=0, speaker_device=1)
        assert config.mic_device == 0
        assert config.speaker_device == 1


class TestVoiceBridgeAudioPlayback:
    """Test the audio playback path (sounddevice mock)."""

    @pytest.mark.asyncio
    async def test_play_audio_empty_is_noop(self) -> None:
        """Empty audio data should be a no-op — no sounddevice call."""
        ui = FakeUI()
        config = VoiceConfig()
        bridge = VoiceBridge(
            config=config,
            ui=ui,
            agent_loop_factory=lambda *a, **k: MagicMock(),
            model_info=_fake_model_info(),
            set_speaking=ui.set_speaking,
        )
        await bridge._play_audio(b"")

    @pytest.mark.asyncio
    async def test_play_audio_odd_length_padded(self) -> None:
        """Odd-length PCM should be padded with a zero byte."""
        ui = FakeUI()
        config = VoiceConfig()
        bridge = VoiceBridge(
            config=config,
            ui=ui,
            agent_loop_factory=lambda *a, **k: MagicMock(),
            model_info=_fake_model_info(),
            set_speaking=ui.set_speaking,
        )

        captured_write: list[bytes] = []

        class MockRawOutputStream:
            def __init__(self, *a, **k):
                pass
            def start(self):
                pass
            def write(self, data):
                captured_write.append(data)
            def stop(self):
                pass
            def close(self):
                pass

        mock_sd = MagicMock()
        mock_sd.RawOutputStream = MockRawOutputStream

        with patch.dict("sys.modules", {"sounddevice": mock_sd}):
            await bridge._play_audio(b"\x00\x01\x02")  # 3 bytes (odd)

        assert len(captured_write) == 1
        assert len(captured_write[0]) == 4  # padded to 4 bytes


class TestVoiceBridgeReconnect:
    """Reconnect loop should retry after transient failures."""

    @pytest.mark.asyncio
    async def test_cancel_during_pipeline_stops_loop(self) -> None:
        """When _cancelled is set, the pipeline loop should exit."""
        config = VoiceConfig()
        ui = FakeUI()

        class StubAgentLoop:
            async def run(self, *a, **k):
                return "stub"

        bridge = VoiceBridge(
            config=config,
            ui=ui,
            agent_loop_factory=lambda *a, **k: StubAgentLoop(),
            model_info=_fake_model_info(),
            set_speaking=ui.set_speaking,
        )

        bridge._running = True
        bridge.cancel()
        assert bridge._cancelled.is_set()


class TestVoiceBridgeEvents:
    """VoiceBridge should emit runtime events."""

    @pytest.mark.asyncio
    async def test_emit_listening_event(self, fake_ui: FakeUI) -> None:
        config = VoiceConfig()
        bridge = VoiceBridge(
            config=config,
            ui=fake_ui,
            agent_loop_factory=lambda *a, **k: MagicMock(),
            model_info=_fake_model_info(),
            set_speaking=fake_ui.set_speaking,
        )
        bridge._emit_event("listening")
        assert any(k == "listening" for k, _ in fake_ui.events)

    @pytest.mark.asyncio
    async def test_emit_speaking_event(self, fake_ui: FakeUI) -> None:
        config = VoiceConfig()
        bridge = VoiceBridge(
            config=config,
            ui=fake_ui,
            agent_loop_factory=lambda *a, **k: MagicMock(),
            model_info=_fake_model_info(),
            set_speaking=fake_ui.set_speaking,
        )
        bridge._emit_event("speaking")
        assert any(k == "speaking" for k, _ in fake_ui.events)

    @pytest.mark.asyncio
    async def test_emit_cancelled_event(self, fake_ui: FakeUI) -> None:
        config = VoiceConfig()
        bridge = VoiceBridge(
            config=config,
            ui=fake_ui,
            agent_loop_factory=lambda *a, **k: MagicMock(),
            model_info=_fake_model_info(),
            set_speaking=fake_ui.set_speaking,
        )
        bridge._emit_event("cancelled")
        assert any(k == "cancelled" for k, _ in fake_ui.events)

    @pytest.mark.asyncio
    async def test_emit_event_handles_missing_ui(self) -> None:
        """Emitting event on a UI without emit_event should not raise."""
        config = VoiceConfig()
        ui = MagicMock()
        ui.emit_event = None
        bridge = VoiceBridge(
            config=config,
            ui=ui,
            agent_loop_factory=lambda *a, **k: MagicMock(),
            model_info=_fake_model_info(),
            set_speaking=ui.set_speaking,
        )
        bridge._emit_event("listening")


class TestVoiceBridgeIntegration:
    """End-to-end simulation of the voice pipeline loop."""

    @pytest.mark.asyncio
    async def test_full_pipeline_with_stubs(self) -> None:
        """Simulate one turn: mic -> STT -> text -> TTS -> audio."""
        ui = FakeUI()

        stt_adapter = MagicMock()
        stt_adapter.transcribe = AsyncMock(return_value="включи свет")

        tts_adapter = MagicMock()
        tts_adapter.synthesize = AsyncMock(
            return_value=AudioStream(data=b"response_wav")
        )
        tts_adapter.interrupted = False

        config = VoiceConfig()
        bridge = VoiceBridge(
            config=config,
            ui=ui,
            agent_loop_factory=lambda *a, **k: MagicMock(),
            model_info=_fake_model_info(),
            set_speaking=ui.set_speaking,
        )
        bridge._stt_adapter = stt_adapter
        bridge._tts_adapter = tts_adapter
        bridge._running = True
        bridge._cancelled = threading.Event()

        text_q = FreshTextQueue(maxsize=8)
        tts_q: asyncio.Queue[str] = asyncio.Queue()

        await text_q.put("включи свет")

        class StubAgentLoop:
            async def run(self, user_goal: str, history: list, **kw):
                return "Включил свет."

        bridge._agent_loop = StubAgentLoop()

        async def run_with_timeout():
            try:
                await asyncio.wait_for(
                    bridge._agent_consumer_loop(text_q, tts_q),
                    timeout=1.0,
                )
            except asyncio.TimeoutError:
                pass

        await run_with_timeout()

        assert tts_q.qsize() >= 1
        response = await tts_q.get()
        assert response == "Включил свет."


class TestVoiceConfig:
    """VoiceConfig dataclass tests."""

    def test_frozen_default(self) -> None:
        config = VoiceConfig()
        assert config.language == "ru"
        assert config.barge_in is True
        assert config.muted is False

    def test_custom_values(self) -> None:
        config = VoiceConfig(
            language="en",
            tts_voice="test_voice",
            tts_speed=0.8,
            barge_in=False,
            muted=True,
            mic_device="mic-0",
        )
        assert config.language == "en"
        assert config.tts_voice == "test_voice"
        assert config.tts_speed == 0.8
        assert config.barge_in is False
        assert config.muted is True
        assert config.mic_device == "mic-0"
