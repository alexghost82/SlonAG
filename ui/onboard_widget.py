"""Onboarding wizard widget — PyQt6 wizard for first-run configuration.

Multi-step wizard shown on first boot when no valid config exists.
Each step is a separate page with validation before advancing.
Secrets go to config/secrets.py, non-secret settings to config/settings.json.
"""

from __future__ import annotations

import platform
import sys

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFont, QKeyEvent
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QRadioButton, QScrollArea, QSpacerItem, QCheckBox,
    QSpinBox, QComboBox, QGroupBox, QVBoxLayout, QWidget, QStackedWidget,
    QProgressBar,
)

from i18n import t
from config.onboard import (
    OnboardState, OnboardResult,
    ALL_STEPS, STEP_LANGUAGE, STEP_PROVIDER, STEP_MODEL, STEP_CREDENTIALS,
    STEP_ENDPOINTS, STEP_PRIVACY, STEP_VOICE, STEP_VISION,
    STEP_MEMORY, STEP_AUTOMATION, STEP_LAN,
    validate_step, run_connection_tests, ConnectionTestResult,
    CLOUD_PROVIDER_IDS, LOCAL_PROVIDER_IDS,
    PROVIDER_IDS,
    CLOUD_MODELS, LOCAL_MODELS,
    STT_ENGINES, TTS_ENGINES,
)

# ─── Color constants (same palette as main UI) ───────────────────────────

_PRI = "#36d6ff"
_PRI_DIM = "#0f4060"
_PRI_GHO = "rgba(54, 214, 255, 0.12)"
_ACC = "#ff6b00"
_ACC2 = "#ffcc00"
_GREEN = "#00ff88"
_GREEN_D = "#00aa55"
_RED = "#ff3355"
_BG = "#00060a"
_BG_S = "#000d12"
_BORDER = "#0d3347"
_BORDER_A = "#0f4060"
_BORDER_B = "#1a5c7a"
_TEXT = "#8ffcff"
_TEXT_DIM = "#3a8a9a"


def _styled(style: str) -> str:
    return style


# ─── Progress indicator ─────────────────────────────────────────────────

class _ProgressBar(QProgressBar):
    def __init__(self, total: int, parent=None):
        super().__init__(parent)
        self.setRange(0, total)
        self.setValue(0)
        self.setTextVisible(True)
        self.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        self.setStyleSheet("""
            QProgressBar {
                background: %s; color: %s; border: 1px solid %s;
                border-radius: 3px; height: 16px; text-align: center;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 %s, stop:1 %s); border-radius: 3px;
            }
        """ % (_BG_S, _TEXT, _BORDER, _PRI, _ACC))


# ─── Connection test display ─────────────────────────────────────────────

class _TestResultBox(QFrame):
    """Shows connection test results."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet(f"""
            QFrame {{ background: {_BG_S}; border: 1px solid {_BORDER}; border-radius: 4px; }}
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        self._title = QLabel(t("onboard.test_dns"))
        self._title.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        self._title.setStyleSheet(f"color: {_TEXT}; background: transparent;")
        layout.addWidget(self._title)

        self._status = QLabel("⋯")
        self._status.setFont(QFont("Courier New", 9))
        self._status.setStyleSheet(f"color: {_TEXT_DIM}; background: transparent;")
        layout.addWidget(self._status)

        self._spinner = QLabel("⏳")
        self._spinner.setFont(QFont("Courier New", 12))
        self._spinner.setStyleSheet(f"color: {_PRI}; background: transparent;")
        self._spinner.setVisible(False)
        layout.addWidget(self._spinner)

        self.setVisible(False)

    def show_ok(self, label: str, message: str):
        self.setVisible(True)
        self._title.setText(label)
        self._status.setText(message)
        self._status.setStyleSheet(f"color: {_GREEN}; background: transparent;")
        self._spinner.setVisible(False)

    def show_fail(self, label: str, message: str):
        self.setVisible(True)
        self._title.setText(label)
        self._status.setText(message)
        self._status.setStyleSheet(f"color: {_RED}; background: transparent;")
        self._spinner.setVisible(False)

    def show_pending(self, label: str):
        self.setVisible(True)
        self._title.setText(label)
        self._status.setText("")
        self._status.setStyleSheet(f"color: {_PRI}; background: transparent;")
        self._spinner.setVisible(True)

    def clear(self):
        self.setVisible(False)


# ─── Step widgets ─────────────────────────────────────────────────────────

class _StepWidget(QWidget):
    """Base class for a single wizard step."""
    def collect(self) -> dict:
        raise NotImplementedError
    def errors(self) -> dict[str, str]:
        return {}


class LanguageStep(_StepWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        self._radio_ru = QRadioButton(t("onboard.lang_ru"))
        self._radio_en = QRadioButton(t("onboard.lang_en"))
        self._radio_ua = QRadioButton(t("onboard.lang_ua"))
        for r in (self._radio_ru, self._radio_en, self._radio_ua):
            r.setFont(QFont("Courier New", 10))
            r.setStyleSheet(f"color: {_TEXT}; background: transparent;")

        self._radio_ru.setChecked(True)
        for r in (self._radio_ru, self._radio_en, self._radio_ua):
            layout.addWidget(r)

        spacer = QSpacerItem(20, 40, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)
        layout.addItem(spacer)

    def collect(self) -> dict:
        if self._radio_ru.isChecked():
            return {"language": "ru"}
        if self._radio_en.isChecked():
            return {"language": "en"}
        return {"language": "uk"}


class ProviderStep(_StepWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        self._combo = QComboBox()
        self._combo.setFont(QFont("Courier New", 10))
        self._combo.setStyleSheet(_provider_combo_style())
        self._combo.addItem("", "")
        for pid in sorted(ALL_PROVIDERS):
            self._combo.addItem(ALL_PROVIDERS[pid].label, pid)
        self._combo.setCurrentIndex(0)

        layout.addWidget(self._combo)
        spacer = QSpacerItem(20, 40, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)
        layout.addItem(spacer)

    def collect(self) -> dict:
        idx = self._combo.currentIndex()
        if idx == 0:
            return {}
        return {"provider_id": self._combo.itemData(idx)}

    def errors(self) -> dict[str, str]:
        if not self._combo.itemData(self._combo.currentIndex()):
            return {"provider": t("onboard.err_select")}
        return {}


class ModelStep(_StepWidget):
    def __init__(self, provider_id: str = "", parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        self._combo = QComboBox()
        self._combo.setFont(QFont("Courier New", 10))
        self._combo.setStyleSheet(_provider_combo_style())

        models = CLOUD_MODELS.get(provider_id, []) if provider_id in CLOUD_PROVIDER_IDS else LOCAL_MODELS.get(provider_id, [])
        if not models:
            models = [("", "Auto (default)")]
        self._combo.addItem("", "")
        for mid, label in models:
            self._combo.addItem(label, mid)
        self._combo.setCurrentIndex(0)

        layout.addWidget(self._combo)
        spacer = QSpacerItem(20, 40, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)
        layout.addItem(spacer)

    def collect(self) -> dict:
        idx = self._combo.currentIndex()
        if idx == 0:
            return {}
        return {"model_id": self._combo.itemData(idx)}

    def update_models(self, provider_id: str) -> None:
        """Refresh model list when provider changes."""
        self._combo.clear()
        models = CLOUD_MODELS.get(provider_id, []) if provider_id in CLOUD_PROVIDER_IDS else LOCAL_MODELS.get(provider_id, [])
        if not models:
            models = [("", "Auto (default)")]
        self._combo.addItem("", "")
        for mid, label in models:
            self._combo.addItem(label, mid)
        self._combo.setCurrentIndex(0)


class CredentialsStep(_StepWidget):
    done = pyqtSignal()

    def __init__(self, provider_id: str = "", parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        is_local = provider_id in LOCAL_PROVIDER_IDS if provider_id else True

        self._key_input = QLineEdit()
        self._key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._key_input.setPlaceholderText(t("onboard.api_key_placeholder"))
        self._key_input.setFont(QFont("Courier New", 10))
        self._key_input.setFixedHeight(32)
        self._key_input.setStyleSheet(_input_style())
        if is_local:
            self._key_input.setEnabled(False)
            self._key_input.setPlaceholderText("🔒 " + t("onboard.key_optional"))
        layout.addWidget(self._key_input)

        self._test_btn = QPushButton(t("onboard.test_key"))
        self._test_btn.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        self._test_btn.setFixedHeight(30)
        self._test_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._test_btn.setStyleSheet(_btn_style())
        self._test_btn.clicked.connect(self._run_test)
        layout.addWidget(self._test_btn)

        self._test_result = _TestResultBox()
        layout.addWidget(self._test_result)

        spacer = QSpacerItem(20, 20, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)
        layout.addItem(spacer)

    def _run_test(self):
        self._test_result.show_pending(t("onboard.test_api"))
        self._test_btn.setEnabled(False)

        provider_id = getattr(self, "_last_provider", "") or ""
        state = OnboardState(step=STEP_CREDENTIALS, provider_id=provider_id)
        setattr(state, f"{provider_id}_api_key", self._key_input.text())

        def _check():
            try:
                results = run_connection_tests(state)
                for r in results:
                    if r.ok:
                        self._test_result.show_ok(r.label, r.message)
                    else:
                        self._test_result.show_fail(r.label, r.message)
            except Exception as exc:
                self._test_result.show_fail("Error", str(exc))
            self._test_btn.setEnabled(True)
            self.done.emit()

        QTimer.singleShot(0, _check)

    def collect(self) -> dict:
        key = self._key_input.text().strip()
        if not key:
            return {}
        pid = getattr(self, "_last_provider", "") or ""
        if pid == "gemini":
            return {"gemini_api_key": key}
        elif pid == "openrouter":
            return {"openrouter_api_key": key}
        elif pid == "openai":
            return {"openai_api_key": key}
        else:
            # Unknown cloud provider — try gemini as default
            return {"gemini_api_key": key}

    @property
    def _provider(self) -> str:
        return getattr(self, "_last_provider", "") or ""

    def errors(self) -> dict[str, str]:
        key = self._key_input.text().strip()
        provider_id = getattr(self, "_last_provider", "") or ""
        if provider_id in CLOUD_PROVIDER_IDS and not key:
            return {"api_key": t("onboard.err_api_required")}
        return {}

    def refresh_for_provider(self, provider_id: str) -> None:
        """Update the credential step when provider changes."""
        self._last_provider = provider_id
        is_local = provider_id in LOCAL_PROVIDER_IDS if provider_id else True
        self._key_input.setEnabled(not is_local)
        if is_local:
            self._key_input.setPlaceholderText("🔒 " + t("onboard.key_optional"))
        else:
            self._key_input.setPlaceholderText(t("onboard.api_key_placeholder"))
        self._key_input.setText("")


class EndpointStep(_StepWidget):
    def __init__(self, provider_id: str = "", parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        default_url = self._default_url(provider_id)
        self._url_input = QLineEdit()
        self._url_input.setPlaceholderText(t("onboard.base_url_placeholder"))
        self._url_input.setText(default_url)
        self._url_input.setFont(QFont("Courier New", 10))
        self._url_input.setFixedHeight(32)
        self._url_input.setStyleSheet(_input_style())
        layout.addWidget(self._url_input)

        self._test_btn = QPushButton(t("onboard.test_key"))
        self._test_btn.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        self._test_btn.setFixedHeight(30)
        self._test_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._test_btn.setStyleSheet(_btn_style())
        self._test_btn.clicked.connect(self._run_test)
        layout.addWidget(self._test_btn)

        self._test_result = _TestResultBox()
        layout.addWidget(self._test_result)

        spacer = QSpacerItem(20, 20, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)
        layout.addItem(spacer)

    def _default_url(self, pid: str) -> str:
        from config.schema import (
            DEFAULT_OPENROUTER_BASE_URL, DEFAULT_LOCAL_BASE_URL,
            DEFAULT_OLLAMA_BASE_URL, DEFAULT_LLAMA_CPP_BASE_URL,
            DEFAULT_OPENAI_COMPAT_BASE_URL,
        )
        if pid == "openrouter":
            return DEFAULT_OPENROUTER_BASE_URL
        if pid == "ollama":
            return DEFAULT_OLLAMA_BASE_URL
        if pid == "llama_cpp":
            return DEFAULT_LLAMA_CPP_BASE_URL
        if pid == "openai_compat":
            return DEFAULT_OPENAI_COMPAT_BASE_URL
        return DEFAULT_LOCAL_BASE_URL

    def _run_test(self):
        url = self._url_input.text().strip()
        if not url:
            self._test_result.show_ok("URL", t("onboard.base_url_optional"))
            return
        from config.onboard import test_dns_lookup, test_http_get
        if url.startswith("https://") or url.startswith("http://"):
            host_part = url.split("://", 1)[1].split("/")[0]
            result = test_dns_lookup(host_part)
            if result.ok:
                self._test_result.show_ok(t("onboard.test_dns"), result.message)
            else:
                self._test_result.show_fail(t("onboard.test_dns"), result.message)
        else:
            self._test_result.show_fail(t("onboard.test_dns"), t("onboard.err_url"))

    def collect(self) -> dict:
        url = self._url_input.text().strip()
        if not url:
            return {}
        return {"provider_base_url": url}

    def errors(self) -> dict[str, str]:
        url = self._url_input.text().strip()
        if url and not (url.startswith("http://") or url.startswith("https://")):
            return {"base_url": t("onboard.err_url")}
        return {}


class PrivacyStep(_StepWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # Privacy profile radio buttons
        profile_group = QGroupBox(t("onboard.step_privacy"))
        profile_group.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        profile_group.setStyleSheet(f"color: {_TEXT}; background: {_BG_S}; border: 1px solid {_BORDER}; border-radius: 4px;")
        profile_layout = QVBoxLayout(profile_group)

        self._priv_fully_local = QRadioButton(t("onboard.privacy_fully_local"))
        self._priv_local_tools = QRadioButton(t("onboard.privacy_local_tools"))
        self._priv_hybrid = QRadioButton(t("onboard.privacy_hybrid"))
        self._priv_cloud = QRadioButton(t("onboard.privacy_cloud"))
        self._priv_fully_local.setData("fully_local")
        self._priv_local_tools.setData("local_with_tools")
        self._priv_hybrid.setData("hybrid")
        self._priv_cloud.setData("cloud")
        for r in (self._priv_fully_local, self._priv_local_tools, self._priv_hybrid, self._priv_cloud):
            r.setFont(QFont("Courier New", 10))
            r.setStyleSheet(f"color: {_TEXT}; background: transparent;")
            profile_layout.addWidget(r)
        self._priv_hybrid.setChecked(True)  # default
        profile_layout.addSpacing(12)

        # Network mode
        net_group = QGroupBox(t("onboard.privacy_net"))
        net_group.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        net_group.setStyleSheet(f"color: {_TEXT}; background: {_BG_S}; border: 1px solid {_BORDER}; border-radius: 4px;")
        net_layout = QVBoxLayout(net_group)

        self._net_offline = QRadioButton(t("onboard.net_offline"))
        self._net_tools = QRadioButton(t("onboard.net_tools"))
        self._net_hybrid = QRadioButton(t("onboard.net_hybrid"))
        self._net_offline.setData("offline")
        self._net_tools.setData("tools_only")
        self._net_hybrid.setData("hybrid")
        for r in (self._net_offline, self._net_tools, self._net_hybrid):
            r.setFont(QFont("Courier New", 10))
            r.setStyleSheet(f"color: {_TEXT}; background: transparent;")
            net_layout.addWidget(r)
        self._net_hybrid.setChecked(True)
        net_layout.addSpacing(12)

        # Routing mode
        route_group = QGroupBox(t("onboard.privacy_routing"))
        route_group.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        route_group.setStyleSheet(f"color: {_TEXT}; background: {_BG_S}; border: 1px solid {_BORDER}; border-radius: 4px;")
        route_layout = QVBoxLayout(route_group)

        self._route_manual = QRadioButton(t("onboard.route_manual"))
        self._route_local_first = QRadioButton(t("onboard.route_local_first"))
        self._route_local_only = QRadioButton(t("onboard.route_local_only"))
        self._route_cloud_first = QRadioButton(t("onboard.route_cloud_first"))
        self._route_manual.setData("manual")
        self._route_local_first.setData("local_first")
        self._route_local_only.setData("local_only")
        self._route_cloud_first.setData("cloud_first")
        for r in (self._route_manual, self._route_local_first, self._route_local_only, self._route_cloud_first):
            r.setFont(QFont("Courier New", 10))
            r.setStyleSheet(f"color: {_TEXT}; background: transparent;")
            route_layout.addWidget(r)
        self._route_manual.setChecked(True)
        route_layout.addSpacing(12)

        layout.addWidget(profile_group)
        layout.addWidget(net_group)
        layout.addWidget(route_group)
        spacer = QSpacerItem(20, 20, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)
        layout.addItem(spacer)

    def collect(self) -> dict:
        return {
            "privacy_profile": self._selected_privacy(),
            "network_mode": self._selected_net(),
            "routing_mode": self._selected_route(),
        }

    def _selected_privacy(self) -> str:
        for r in (self._priv_fully_local, self._priv_local_tools, self._priv_hybrid, self._priv_cloud):
            if r.isChecked():
                return r.data() or "hybrid"
        return "hybrid"

    def _selected_net(self) -> str:
        for r in (self._net_offline, self._net_tools, self._net_hybrid):
            if r.isChecked():
                return r.data() or "hybrid"
        return "hybrid"

    def _selected_route(self) -> str:
        for r in (self._route_manual, self._route_local_first, self._route_local_only, self._route_cloud_first):
            if r.isChecked():
                return r.data() or "manual"
        return "manual"


class VoiceStep(_StepWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        self._stt_combo = QComboBox()
        self._stt_combo.setFont(QFont("Courier New", 10))
        self._stt_combo.setStyleSheet(_provider_combo_style())
        for engine, label in STT_ENGINES:
            self._stt_combo.addItem(label, engine)
        self._stt_combo.setCurrentIndex(0)
        layout.addWidget(QLabel(t("onboard.voice_stt")))
        layout.addWidget(self._stt_combo)

        self._tts_combo = QComboBox()
        self._tts_combo.setFont(QFont("Courier New", 10))
        self._tts_combo.setStyleSheet(_provider_combo_style())
        for engine, label in TTS_ENGINES:
            self._tts_combo.addItem(label, engine)
        self._tts_combo.setCurrentIndex(0)
        layout.addWidget(QLabel(t("onboard.voice_tts")))
        layout.addWidget(self._tts_combo)

        self._mic_combo = QComboBox()
        self._mic_combo.setFont(QFont("Courier New", 10))
        self._mic_combo.setStyleSheet(_provider_combo_style())
        self._mic_combo.addItem(t("onboard.voice_auto"), "")
        layout.addWidget(QLabel(t("onboard.voice_mic")))
        layout.addWidget(self._mic_combo)

        self._speaker_combo = QComboBox()
        self._speaker_combo.setFont(QFont("Courier New", 10))
        self._speaker_combo.setStyleSheet(_provider_combo_style())
        self._speaker_combo.addItem(t("onboard.voice_auto"), "")
        layout.addWidget(QLabel(t("onboard.voice_speaker")))
        layout.addWidget(self._speaker_combo)

        # Detect available devices
        self._detect_devices()

        spacer = QSpacerItem(20, 20, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)
        layout.addItem(spacer)

    def _detect_devices(self):
        """Detect available audio devices (best effort)."""
        try:
            import sounddevice as sd
            devices = sd.query_devices()
            for i, dev in enumerate(devices):
                if dev.get("max_input_channels", 0) > 0:
                    self._mic_combo.addItem(f"Input: {dev.get('name', str(i))}", str(i))
                if dev.get("max_output_channels", 0) > 0:
                    self._speaker_combo.addItem(f"Output: {dev.get('name', str(i))}", str(i))
        except Exception:
            pass  # sounddevice not available; fall back to default

    def collect(self) -> dict:
        stt = self._stt_combo.itemData(self._stt_combo.currentIndex())
        tts = self._tts_combo.itemData(self._tts_combo.currentIndex())
        mic = self._mic_combo.itemData(self._mic_combo.currentIndex())
        speaker = self._speaker_combo.itemData(self._speaker_combo.currentIndex())
        result = {}
        if stt and stt != "":
            result["voice_stt_engine"] = stt
        if tts and tts != "":
            result["voice_tts_engine"] = tts
        if mic:
            result["voice_mic_device"] = mic
        if speaker:
            result["voice_speaker_device"] = speaker
        return result

    def errors(self) -> dict[str, str]:
        stt = self._stt_combo.itemData(self._stt_combo.currentIndex())
        tts = self._tts_combo.itemData(self._tts_combo.currentIndex())
        errors = {}
        if stt and stt not in [e for e, _ in STT_ENGINES]:
            errors["stt"] = t("onboard.err_invalid_stt")
        if tts and tts not in [e for e, _ in TTS_ENGINES]:
            errors["tts"] = t("onboard.err_invalid_tts")
        return errors


class VisionStep(_StepWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        self._enable_check = QCheckBox(t("onboard.vision_enabled"))
        self._enable_check.setFont(QFont("Courier New", 10))
        self._enable_check.setStyleSheet(f"color: {_TEXT}; background: transparent;")
        self._enable_check.setChecked(True)
        layout.addWidget(self._enable_check)

        self._camera_spin = QSpinBox()
        self._camera_spin.setRange(0, 16)
        self._camera_spin.setValue(0)
        self._camera_spin.setFont(QFont("Courier New", 10))
        layout.addWidget(QLabel(t("onboard.vision_camera_idx")))
        layout.addWidget(self._camera_spin)

        self._rtsp_input = QLineEdit()
        self._rtsp_input.setPlaceholderText(t("onboard.vision_rtsp_placeholder"))
        self._rtsp_input.setFont(QFont("Courier New", 10))
        self._rtsp_input.setFixedHeight(32)
        self._rtsp_input.setStyleSheet(_input_style())
        layout.addWidget(QLabel(t("onboard.vision_rtsp_url")))
        layout.addWidget(self._rtsp_input)

        spacer = QSpacerItem(20, 20, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)
        layout.addItem(spacer)

    def collect(self) -> dict:
        result = {"vision_enabled": self._enable_check.isChecked()}
        if self._camera_spin.value() > 0:
            result["camera_index"] = self._camera_spin.value()
        rtsp = self._rtsp_input.text().strip()
        if rtsp:
            result["rtsp_url"] = rtsp
        return result


class ToggleStep(_StepWidget):
    def __init__(self, key: str, title: str, hint: str, default: bool = True, parent=None):
        super().__init__(parent)
        self._key = key
        layout = QVBoxLayout(self)

        self._check = QCheckBox(title)
        self._check.setFont(QFont("Courier New", 10))
        self._check.setStyleSheet(f"color: {_TEXT}; background: transparent;")
        self._check.setChecked(default)
        layout.addWidget(self._check)

        hint_label = QLabel(hint)
        hint_label.setFont(QFont("Courier New", 9))
        hint_label.setStyleSheet(f"color: {_TEXT_DIM}; background: transparent;")
        layout.addWidget(hint_label)

    def collect(self) -> dict:
        return {self._key: self._check.isChecked()}


class MemoryStep(_StepWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._chk = ToggleStep(
            "memory_enabled",
            t("onboard.memory_enabled"),
            t("onboard.memory_hint"),
            default=True,
            parent=self,
        )
        layout = QVBoxLayout(self)
        layout.addWidget(self._chk)
        spacer = QSpacerItem(20, 20, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)
        layout.addItem(spacer)

    def collect(self) -> dict:
        return self._chk.collect()


class AutomationStep(_StepWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)

        self._auto_chk = ToggleStep(
            "automation_enabled",
            t("onboard.automation_enabled"),
            t("onboard.automation_hint"),
            default=True,
            parent=self,
        )
        layout.addWidget(self._auto_chk)

        self._browser_chk = ToggleStep(
            "browser_enabled",
            t("onboard.browser_enabled"),
            t("onboard.browser_hint"),
            default=True,
            parent=self,
        )
        layout.addWidget(self._browser_chk)

        spacer = QSpacerItem(20, 20, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)
        layout.addItem(spacer)

    def collect(self) -> dict:
        result = {}
        result.update(self._auto_chk.collect())
        result.update(self._browser_chk.collect())
        return result


class LanStep(_StepWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)

        self._lan_chk = ToggleStep(
            "lan_enabled",
            t("onboard.lan_enabled"),
            t("onboard.lan_hint"),
            default=False,
            parent=self,
        )
        layout.addWidget(self._lan_chk)

        self._remote_chk = ToggleStep(
            "remote_transport",
            t("onboard.remote_enabled"),
            "",
            default=False,
            parent=self,
        )
        layout.addWidget(self._remote_chk)

        self._remote_input = QLineEdit()
        self._remote_input.setPlaceholderText(t("onboard.remote_placeholder"))
        self._remote_input.setFont(QFont("Courier New", 10))
        self._remote_input.setFixedHeight(32)
        self._remote_input.setStyleSheet(_input_style())
        self._remote_input.setVisible(False)
        layout.addWidget(QLabel(t("onboard.remote_url")))
        layout.addWidget(self._remote_input)

        self._remote_chk._check.stateChanged.connect(
            lambda s: self._remote_input.setVisible(s == 2)
        )

        spacer = QSpacerItem(20, 20, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)
        layout.addItem(spacer)

    def collect(self) -> dict:
        result = self._lan_chk.collect()
        if self._remote_chk.collect().get("remote_transport", False):
            result["remote_transport"] = "http"
            url = self._remote_input.text().strip()
            if url:
                result["remote_base_url"] = url
        return result


class CompleteStep(_StepWidget):
    done = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        lbl = QLabel("✓")
        lbl.setFont(QFont("Courier New", 28, QFont.Weight.Bold))
        lbl.setStyleSheet(f"color: {_GREEN}; background: transparent;")
        layout.addWidget(lbl)

        title = QLabel(t("onboard.title"))
        title.setFont(QFont("Courier New", 14, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(f"color: {_TEXT}; background: transparent;")
        layout.addWidget(title)

        sub = QLabel(t("onboard.restart_prompt"))
        sub.setFont(QFont("Courier New", 9))
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setStyleSheet(f"color: {_TEXT_DIM}; background: transparent;")
        layout.addWidget(sub)

        layout.addSpacing(20)
        self._save_btn = QPushButton(t("onboard.complete"))
        self._save_btn.setFont(QFont("Courier New", 11, QFont.Weight.Bold))
        self._save_btn.setFixedHeight(40)
        self._save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._save_btn.setStyleSheet(_btn_style(_GREEN))
        self._save_btn.clicked.connect(self._submit)
        layout.addWidget(self._save_btn)

        self._saving = False

    def _submit(self):
        if self._saving:
            return
        self._saving = True
        self._save_btn.setText(t("onboard.saving"))
        self._save_btn.setEnabled(False)
        self.done.emit()

    def show_error(self, msg: str) -> None:
        lbl = QLabel(msg)
        lbl.setFont(QFont("Courier New", 9))
        lbl.setStyleSheet(f"color: {_RED}; background: {_BG_S}; border-radius: 3px; padding: 8px; margin-top: 12px;")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._save_btn.parent().layout().insertWidget(0, lbl)
        self._save_btn.setEnabled(True)
        self._save_btn.setText(t("onboard.complete"))


# ─── Main wizard widget ───────────────────────────────────────────────────

class OnboardingWizard(QWidget):
    """Multi-step onboarding wizard."""

    done = pyqtSignal(OnboardResult)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._state = OnboardState()
        self._steps: dict = {
            STEP_LANGUAGE: LanguageStep(),
            STEP_PROVIDER: ProviderStep(),
            STEP_MODEL: ModelStep(),
            STEP_CREDENTIALS: CredentialsStep(),
            STEP_ENDPOINTS: EndpointStep(),
            STEP_PRIVACY: PrivacyStep(),
            STEP_VOICE: VoiceStep(),
            STEP_VISION: VisionStep(),
            STEP_MEMORY: MemoryStep(),
            STEP_AUTOMATION: AutomationStep(),
            STEP_LAN: LanStep(),
        }
        self._complete = CompleteStep()
        self._test_results: list[_TestResultBox] = []

        # ── Layout ──────────────────────────────────────────────────────
        self.setStyleSheet(f"""
            QWidget {{ background: {_BG}; }}
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(6)

        # Title
        title = QLabel(t("onboard.title"))
        title.setFont(QFont("Courier New", 14, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(f"color: {_PRI}; background: transparent;")
        root.addWidget(title)

        subtitle = QLabel(t("onboard.subtitle"))
        subtitle.setFont(QFont("Courier New", 9))
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setStyleSheet(f"color: {_TEXT_DIM}; background: transparent;")
        root.addWidget(subtitle)

        # Progress (ALL_STEPS doesn't include STEP_COMPLETE)
        self._progress = _ProgressBar(len(ALL_STEPS))
        root.addWidget(self._progress)

        # Separator
        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {_BORDER};")
        root.addWidget(sep)

        # Step stack (one page at a time)
        self._stack = QStackedWidget()
        self._stack.setStyleSheet(f"background: transparent;")

        # Populate stack with step widgets wrapped in scroll areas
        for step_id in ALL_STEPS:
            sw = self._steps[step_id]
            if isinstance(sw, CompleteStep):
                continue
            scroll = QScrollArea()
            scroll.setWidget(sw)
            scroll.setWidgetResizable(True)
            scroll.setStyleSheet("background: transparent; border: none;")
            self._stack.addWidget(scroll)

        # Add complete step
        self._stack.addWidget(self._complete)
        root.addWidget(self._stack, stretch=1)

        # Separator
        sep2 = QFrame(); sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet(f"color: {_BORDER};")
        root.addWidget(sep2)

        # Navigation buttons
        nav = QHBoxLayout()
        nav.setSpacing(12)

        self._back_btn = QPushButton(t("onboard.back"))
        self._back_btn.setFont(QFont("Courier New", 10, QFont.Weight.Bold))
        self._back_btn.setFixedHeight(36)
        self._back_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._back_btn.setStyleSheet(_btn_style())
        self._back_btn.clicked.connect(self._go_back)
        nav.addWidget(self._back_btn)

        self._next_btn = QPushButton(t("onboard.next"))
        self._next_btn.setFont(QFont("Courier New", 10, QFont.Weight.Bold))
        self._next_btn.setFixedHeight(36)
        self._next_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._next_btn.setStyleSheet(_btn_style())
        self._next_btn.clicked.connect(self._go_next)
        nav.addWidget(self._next_btn)

        root.addLayout(nav)

        self._current_idx = 0
        self._update_ui()

        # Signal connections
        self._steps[STEP_PROVIDER]._combo.currentIndexChanged.connect(self._on_provider_change)
        self._complete.done.connect(self._on_complete_done)

    # ── Navigation ──────────────────────────────────────────────────────

    def _update_ui(self):
        self._stack.setCurrentIndex(self._current_idx)
        self._progress.setValue(self._current_idx)

        # Back button
        self._back_btn.setVisible(self._current_idx > 0)

        # Next button
        is_complete = self._current_idx >= len(ALL_STEPS)
        if is_complete:
            self._next_btn.setVisible(False)
        else:
            self._next_btn.setVisible(True)
            self._next_btn.setText(t("onboard.next"))

    def _go_next(self):
        """Validate current step and advance."""
        step_id = ALL_STEPS[self._current_idx]
        widget = self._steps.get(step_id)
        if not widget:
            return

        # Collect and validate
        errors = widget.errors() if hasattr(widget, "errors") else {}
        if errors:
            # Show error
            lbl = QLabel(f"⚠ {list(errors.values())[0]}", self)
            lbl.setFont(QFont("Courier New", 10))
            lbl.setStyleSheet(f"color: {_RED}; background: {_BG_S}; border-radius: 3px; padding: 8px;")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._stack.addWidget(lbl)
            self._stack.setCurrentWidget(lbl)
            QTimer.singleShot(2000, lambda: self._stack.setCurrentIndex(self._current_idx))
            return

        # Advance
        self._collect_step_data(step_id, widget)
        if self._current_idx < len(ALL_STEPS):
            self._current_idx += 1
        self._update_ui()

    def _collect_step_data(self, step_id, widget):
        """Store collected data from a step into self._state."""
        data = widget.collect() if hasattr(widget, "collect") else {}
        if step_id == STEP_LANGUAGE:
            self._state.language = data.get("language", "ru")
        elif step_id == STEP_PROVIDER:
            self._state.provider_id = data.get("provider_id", "")
            if self._state.provider_id in ("ollama", "llama_cpp"):
                self._state.local_provider = self._state.provider_id
        elif step_id == STEP_MODEL:
            self._state.model_id = data.get("model_id", "")
        elif step_id == STEP_CREDENTIALS:
            # Credentials are stored separately via _on_complete_done
            pass
        elif step_id == STEP_ENDPOINTS:
            self._state.provider_base_url = data.get("provider_base_url", "")
        elif step_id == STEP_PRIVACY:
            self._state.privacy_profile = data.get("privacy_profile", "fully_local")
            self._state.network_mode = data.get("network_mode", "hybrid")
            self._state.routing_mode = data.get("routing_mode", "local_first")
        elif step_id == STEP_VOICE:
            self._state.stt_engine = data.get("stt_engine", "faster_whisper")
            self._state.tts_engine = data.get("tts_engine", "piper")
            self._state.mic_device = data.get("mic_device")
            self._state.speaker_device = data.get("speaker_device")
        elif step_id == STEP_VISION:
            self._state.vision_enabled = data.get("vision_enabled", False)
            self._state.camera_enabled = data.get("camera_enabled", False)
            self._state.camera_index = data.get("camera_index")
            self._state.rtsp_enabled = data.get("rtsp_enabled", False)
            self._state.rtsp_url = data.get("rtsp_url", "")
        elif step_id == STEP_MEMORY:
            self._state.memory_enabled = data.get("memory_enabled", False)
        elif step_id == STEP_AUTOMATION:
            self._state.automation_enabled = data.get("automation_enabled", False)
        elif step_id == STEP_LAN:
            self._state.lan_enabled = data.get("lan_enabled", False)
            self._state.remote_transport = data.get("remote_transport", "none")
            self._state.remote_base_url = data.get("remote_base_url", "")
        # STEP_ENDPOINTS collects only provider_base_url (URL) widget

    def _go_back(self):
        if self._current_idx > 0:
            self._current_idx -= 1
            self._update_ui()

    def _on_provider_change(self):
        """When provider changes, update model and credential steps."""
        idx = self._steps[STEP_PROVIDER]._combo.currentIndex()
        if idx == 0:
            return
        provider_id = self._steps[STEP_PROVIDER]._combo.itemData(idx)
        self._state.provider_id = provider_id

        # Update model step with new provider's models
        model_step = self._steps.get(STEP_MODEL)
        if model_step:
            model_step.update_models(provider_id)

        # Update credentials step with new provider
        cred_step = self._steps[STEP_CREDENTIALS]
        cred_step.refresh_for_provider(provider_id)

    # ── Final submission ────────────────────────────────────────────────

    def _on_complete_done(self):
        """Handle Apply & Restart button."""
        from config.onboard import apply_onboard_result, OnboardResult
        
        # Build result from collected state
        try:
            state = self._state.build_result()
            result = OnboardResult(state=state)

            # Collect provider credentials from the credential step
            cred_step = self._steps.get(STEP_CREDENTIALS)
            gemini_key = ""
            openrouter_key = ""
            openai_key = ""
            if cred_step:
                key_text = cred_step._key_input.text().strip() if hasattr(cred_step, "_key_input") else ""
                pid = cred_step._last_provider if hasattr(cred_step, "_last_provider") else self._state.provider_id
                if pid == "gemini":
                    gemini_key = key_text
                elif pid == "openrouter":
                    openrouter_key = key_text
                elif pid == "openai":
                    openai_key = key_text
                else:
                    # For openai_compat or unknown, try all
                    gemini_key = key_text

            apply_onboard_result(result, gemini_key, openrouter_key, openai_key)
        except Exception as exc:
            lbl = QLabel(f"✗ {t('onboard.err_unknown')}: {exc}", self)
            lbl.setFont(QFont("Courier New", 10))
            lbl.setStyleSheet(f"color: {_RED}; background: {_BG_S}; border-radius: 3px; padding: 8px;")
            self._stack.addWidget(lbl)
            self._stack.setCurrentWidget(lbl)
            self._complete._save_btn.setEnabled(True)
            self._complete._save_btn.setText(t("onboard.complete"))
            return

        # Emit result and hide
        self.done.emit(result)
        self.hide()


# ─── Style helpers ────────────────────────────────────────────────────────

def _input_style() -> str:
    return f"""
        QLineEdit {{
            background: {_BG_S}; color: {_TEXT};
            border: 1px solid {_BORDER}; border-radius: 3px; padding: 4px 8px;
        }}
        QLineEdit:focus {{ border: 1px solid {_PRI}; }}
    """


def _btn_style(hover_color: str = _PRI_GHO) -> str:
    return f"""
        QPushButton {{
            background: transparent; color: {_PRI};
            border: 1px solid {_PRI_DIM}; border-radius: 3px;
        }}
        QPushButton:hover {{
            background: {hover_color}; border: 1px solid {_PRI};
        }}
        QPushButton:disabled {{
            color: {_TEXT_DIM}; border: 1px solid {_BORDER};
        }}
    """


def _provider_combo_style() -> str:
    return f"""
        QComboBox {{
            background: {_BG_S}; color: {_TEXT};
            border: 1px solid {_BORDER}; border-radius: 3px; padding: 4px 8px;
            min-width: 200px;
        }}
        QComboBox::drop-down {{ border: none; }}
        QComboBox QAbstractItemView {{
            background: {_BG_S}; color: {_TEXT}; selection-background-color: {_PRI_DIM};
        }}
    """
