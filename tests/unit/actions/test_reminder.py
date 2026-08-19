"""Reminder action: JSON store, no generated Python, no shell=True."""

from __future__ import annotations

import inspect
import json
import subprocess
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from actions.reminder import reminder
from mark.safety import DecisionKind, RiskLevel, UntrustedSource, authorize, risk_for

INJECTED_MESSAGE = 'hello"; rm -rf / # \'quoted\''
FUTURE = {"date": "2099-01-01", "time": "10:00", "message": INJECTED_MESSAGE}


class RecordingScheduler:
    def __init__(self, returncode: int = 0) -> None:
        self.calls: list[list[str]] = []
        self.returncode = returncode
        self.stdout = ""
        self.stderr = ""

    def __call__(self, argv: list[str]) -> RecordingScheduler:
        assert isinstance(argv, list)
        assert all(isinstance(part, str) for part in argv)
        self.calls.append(list(argv))
        return self


def _create(
    tmp_path: Path,
    *,
    os_name: str = "windows",
    scheduler: RecordingScheduler | None = None,
    confirmer=lambda _decision: True,
    extra: dict | None = None,
    source: str = "user",
) -> tuple[str, RecordingScheduler]:
    sched = scheduler if scheduler is not None else RecordingScheduler()
    params = dict(FUTURE)
    if extra:
        params.update(extra)
    result = reminder(
        parameters=params,
        store_path=tmp_path / "reminders.json",
        os_name=os_name,
        scheduler=sched,
        confirmer=confirmer,
        source=source,
        now=datetime(2026, 8, 15, 8, 0),
    )
    return result, sched


def _store(tmp_path: Path) -> dict:
    return json.loads((tmp_path / "reminders.json").read_text(encoding="utf-8"))


def test_risk_for_reminder_is_confirm() -> None:
    assert risk_for("reminder") == RiskLevel.CONFIRM
    assert int(risk_for("reminder")) == 2


def test_list_is_allow_mutating_and_legacy_are_confirm() -> None:
    listed = authorize("reminder", {"action": "list"}, source=UntrustedSource.USER)
    assert listed.kind == DecisionKind.ALLOW
    assert listed.risk == RiskLevel.READ

    for args in (
        {"action": "create", **FUTURE},
        {"action": "update", "id": "abc", "message": "x"},
        {"action": "cancel", "id": "abc"},
        FUTURE,
    ):
        decision = authorize("reminder", args, source=UntrustedSource.USER)
        assert decision.kind == DecisionKind.CONFIRM
        assert decision.risk == RiskLevel.CONFIRM


def test_no_shell_true_in_source() -> None:
    import actions.reminder as module

    source = inspect.getsource(module)
    assert "shell=True" not in source
    file_text = Path(module.__file__).read_text(encoding="utf-8")
    assert "shell=True" not in file_text


def test_user_message_is_not_written_to_python_file(tmp_path: Path) -> None:
    result, _sched = _create(tmp_path)
    assert "Reminder set" in result
    assert INJECTED_MESSAGE not in result

    generated = list(tmp_path.rglob("*.py")) + list(tmp_path.rglob("*.pyw"))
    assert generated == []

    payload = _store(tmp_path)
    assert payload["reminders"][0]["message"] == INJECTED_MESSAGE


def test_windows_xml_is_elementtree_not_shell_interpolation(tmp_path: Path) -> None:
    result, sched = _create(tmp_path, os_name="windows")
    assert "id:" in result
    assert sched.calls
    assert sched.calls[0][0] == "schtasks"
    assert "/XML" in sched.calls[0]
    xml_path = Path(sched.calls[0][sched.calls[0].index("/XML") + 1])
    assert xml_path.is_file()
    root = ET.parse(xml_path).getroot()
    assert root.tag.endswith("Task")
    xml_text = xml_path.read_text(encoding="utf-16")
    assert INJECTED_MESSAGE not in xml_text
    assert "schtasks /Create" not in xml_text


def test_list_update_cancel_use_json_store(tmp_path: Path) -> None:
    created, sched = _create(tmp_path, extra={"action": "create"})
    reminder_id = _store(tmp_path)["reminders"][0]["id"]
    assert reminder_id in created

    listed = reminder(
        parameters={"action": "list"},
        store_path=tmp_path / "reminders.json",
        os_name="windows",
        scheduler=sched,
    )
    assert reminder_id in listed
    assert INJECTED_MESSAGE in listed

    updated = reminder(
        parameters={"action": "update", "id": reminder_id, "message": "stand up"},
        store_path=tmp_path / "reminders.json",
        os_name="windows",
        scheduler=sched,
        confirmer=lambda _decision: True,
        now=datetime(2026, 8, 15, 8, 0),
    )
    assert reminder_id in updated
    assert _store(tmp_path)["reminders"][0]["message"] == "stand up"

    cancelled = reminder(
        parameters={"action": "cancel", "id": reminder_id},
        store_path=tmp_path / "reminders.json",
        os_name="windows",
        scheduler=sched,
        confirmer=lambda _decision: True,
    )
    assert reminder_id in cancelled
    assert _store(tmp_path)["reminders"] == []
    empty = reminder(
        parameters={"op": "list"},
        store_path=tmp_path / "reminders.json",
        os_name="windows",
        scheduler=sched,
    )
    assert empty == "No reminders."


def test_macos_backend_uses_injected_scheduler(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _blocked(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("real osascript / subprocess must not run")

    monkeypatch.setattr(subprocess, "run", _blocked)
    monkeypatch.setattr(subprocess, "Popen", _blocked)
    result, sched = _create(tmp_path, os_name="macos")
    assert "Reminder set" in result
    assert sched.calls
    assert sched.calls[0][0] == "osascript"
    assert "--schedule" in sched.calls[0]
    assert INJECTED_MESSAGE not in " ".join(sched.calls[0])


def test_linux_backend_uses_injected_scheduler(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _blocked(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("real at / subprocess must not run")

    monkeypatch.setattr(subprocess, "run", _blocked)
    monkeypatch.setattr(subprocess, "Popen", _blocked)
    result, sched = _create(tmp_path, os_name="linux")
    assert "Reminder set" in result
    assert sched.calls
    assert sched.calls[0][0] == "at"
    assert "-t" in sched.calls[0]
    assert INJECTED_MESSAGE not in " ".join(sched.calls[0])


def test_untrusted_source_does_not_create(tmp_path: Path) -> None:
    sched = RecordingScheduler()
    result = reminder(
        parameters=dict(FUTURE),
        store_path=tmp_path / "reminders.json",
        os_name="linux",
        scheduler=sched,
        source=UntrustedSource.DOCUMENT,
    )
    assert "not allowed" in result.lower()
    assert not (tmp_path / "reminders.json").exists()
    assert sched.calls == []


def test_rejected_confirm_does_not_mutate(tmp_path: Path) -> None:
    result, sched = _create(tmp_path, confirmer=lambda _decision: False)
    assert "not confirmed" in result.lower()
    assert not (tmp_path / "reminders.json").exists()
    assert sched.calls == []


def test_legacy_date_time_message_creates(tmp_path: Path) -> None:
    result, _sched = _create(tmp_path)
    assert "Reminder set" in result
    assert len(_store(tmp_path)["reminders"]) == 1
