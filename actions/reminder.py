"""Schedule reminders from a JSON store. Never interpolates user text into Python."""

from __future__ import annotationsfrom i18n import t


import json
import os
import platform
import subprocess
import sys
import uuid
from collections.abc import Callable, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from mark.safety import authorize, validate_args
from mark.safety.errors import ArgValidationError
from mark.safety.types import DecisionKind

_TASK_NS = "http://schemas.microsoft.com/windows/2004/02/mit/task"
_OPS = frozenset({"create", "list", "update", "cancel"})
_MUTATING = frozenset({"create", "update", "cancel"})
_OS_ALIASES = {
    "windows": "windows",
    "win32": "windows",
    "win": "windows",
    "darwin": "macos",
    "macos": "macos",
    "mac": "macos",
    "linux": "linux",
}

Scheduler = Callable[[list[str]], Any]
Confirmer = Callable[[Any], bool]


def reminder(
    parameters: dict,
    response: str | None = None,
    player=None,
    session_memory=None,
    *,
    store_path: str | Path | None = None,
    os_name: str | None = None,
    scheduler: Scheduler | None = None,
    confirmer: Confirmer | None = None,
    source: str = "user",
    now: datetime | None = None,
) -> str:
    """Create, list, update, or cancel a reminder.

    The executor entry is ``reminder(parameters=..., player=None)``. Tests
    inject ``store_path``, ``os_name``, and ``scheduler`` so no real
    ``schtasks`` / ``osascript`` / ``at`` runs.
    """
    del response, session_memory
    try:
        checked = validate_args("reminder", parameters)
    except ArgValidationError:
        return "Неверный формат аргументов напоминания."

    try:
        backend = _normalize_os(os_name)
        path = Path(store_path) if store_path is not None else _default_store_path()
        op = _resolve_op(checked)
        if op not in _OPS:
            return "Неизвестное действие напоминания."

        if op in _MUTATING:
            blocked = _authorize_mutation(checked, source=source, confirmer=confirmer)
            if blocked is not None:
                return blocked

        if op == "list":
            return _list_reminders(path)

        if op == "cancel":
            return _cancel_reminder(checked, path, backend, scheduler, player)

        return _upsert_reminder(
            checked,
            path=path,
            backend=backend,
            scheduler=scheduler,
            player=player,
            now=now,
            replacing=op == "update",
        )
    except ValueError:
        return "Не удалось распознать формат даты или времени."
    except Exception as exc:
        return f"Не удалось запланировать напоминание: {str(exc)[:80]}"


def build_windows_task_xml(
    *,
    start: datetime,
    command: str,
    arguments: str,
    description: str,
) -> ET.Element:
    """Build a Task Scheduler document. User text is XML-escaped, not shelled."""
    ET.register_namespace("", _TASK_NS)

    def tag(name: str) -> str:
        return f"{{{_TASK_NS}}}{name}"

    task = ET.Element(tag("Task"), {"version": "1.2"})
    info = ET.SubElement(task, tag("RegistrationInfo"))
    ET.SubElement(info, tag("Description")).text = description
    triggers = ET.SubElement(task, tag("Triggers"))
    trigger = ET.SubElement(triggers, tag("TimeTrigger"))
    ET.SubElement(trigger, tag("StartBoundary")).text = start.strftime("%Y-%m-%dT%H:%M:%S")
    ET.SubElement(trigger, tag("Enabled")).text = "true"
    actions = ET.SubElement(task, tag("Actions"))
    exe = ET.SubElement(actions, tag("Exec"))
    ET.SubElement(exe, tag("Command")).text = command
    ET.SubElement(exe, tag("Arguments")).text = arguments
    settings = ET.SubElement(task, tag("Settings"))
    ET.SubElement(settings, tag("MultipleInstancesPolicy")).text = "IgnoreNew"
    ET.SubElement(settings, tag("DisallowStartIfOnBatteries")).text = "false"
    ET.SubElement(settings, tag("StopIfGoingOnBatteries")).text = "false"
    ET.SubElement(settings, tag("StartWhenAvailable")).text = "true"
    ET.SubElement(settings, tag("WakeToRun")).text = "true"
    ET.SubElement(settings, tag("ExecutionTimeLimit")).text = "PT5M"
    ET.SubElement(settings, tag("Enabled")).text = "true"
    principals = ET.SubElement(task, tag("Principals"))
    principal = ET.SubElement(principals, tag("Principal"))
    ET.SubElement(principal, tag("LogonType")).text = "InteractiveToken"
    ET.SubElement(principal, tag("RunLevel")).text = "LeastPrivilege"
    return task


def write_windows_task_xml(path: Path, root: ET.Element) -> None:
    """Serialize ``root`` as UTF-16 Task Scheduler XML."""
    path.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(root).write(
        path,
        encoding="utf-16",
        xml_declaration=True,
    )


def _resolve_op(parameters: Mapping[str, object]) -> str:
    for key in ("action", "op"):
        value = parameters.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().lower()
    return "create"


def _normalize_os(os_name: str | None) -> str:
    raw = (os_name if os_name is not None else platform.system()).strip().lower()
    backend = _OS_ALIASES.get(raw)
    if backend is None:
        raise RuntimeError(t("error.unsupported_reminder_os", raw=raw))
    return backend


def _default_store_path() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or os.environ.get("TEMP") or ".")
    else:
        xdg = os.environ.get("XDG_DATA_HOME")
        base = Path(xdg) if xdg else Path.home() / ".local" / "share"
    return base / "mark" / "reminders.json"


def _authorize_mutation(
    parameters: Mapping[str, object],
    *,
    source: str,
    confirmer: Confirmer | None,
) -> str | None:
    decision = authorize("reminder", parameters, source=source, intent="reminder")
    if decision.kind == DecisionKind.DENY:
        return "That reminder action is not allowed."
    needs_confirm = decision.kind in {
        DecisionKind.CONFIRM,
        DecisionKind.EXACT_CONFIRM,
        DecisionKind.BIOMETRIC,
    }
    if needs_confirm and confirmer is not None and not confirmer(decision):
        return "Изменение напоминания не подтверждено."
    return None


def _list_reminders(store_path: Path) -> str:
    items = _load_store(store_path)
    if not items:
        return "Нет напоминаний."
    lines = ["Reminders:"]
    for item in items:
        lines.append(
            f"- {item['id']}: {item['date']} {item['time']} — {item['message']}"
        )
    return "\n".join(lines)


def _cancel_reminder(
    parameters: Mapping[str, object],
    store_path: Path,
    backend: str,
    scheduler: Scheduler | None,
    player: Any,
) -> str:
    reminder_id = _require_id(parameters)
    if reminder_id is None:
        return "Необходим ID напоминания для отмены."
    items = _load_store(store_path)
    found = next((item for item in items if item["id"] == reminder_id), None)
    if found is None:
        return "Напоминание с таким ID не найдено."
    _unschedule(backend, found, scheduler)
    _save_store(store_path, [item for item in items if item["id"] != reminder_id])
    _log(player, f"[reminder] cancelled {reminder_id}")
    return f"Reminder {reminder_id} cancelled."


def _upsert_reminder(
    parameters: Mapping[str, object],
    *,
    path: Path,
    backend: str,
    scheduler: Scheduler | None,
    player: Any,
    now: datetime | None,
    replacing: bool,
) -> str:
    items = _load_store(path)
    existing = None
    if replacing:
        reminder_id = _require_id(parameters)
        if reminder_id is None:
            return "Необходим ID напоминания для обновления."
        existing = next((item for item in items if item["id"] == reminder_id), None)
        if existing is None:
            return "Напоминание с таким ID не найдено."
        date_str = _optional_str(parameters, "date") or existing["date"]
        time_str = _optional_str(parameters, "time") or existing["time"]
        message = _optional_str(parameters, "message")
        if message is None:
            message = existing["message"]
        reminder_id = existing["id"]
        task_name = existing["task_name"]
    else:
        date_str = _optional_str(parameters, "date")
        time_str = _optional_str(parameters, "time")
        if not date_str or not time_str:
            return "Укажите дату и время для напоминания."
        message = _optional_str(parameters, "message") or "Напоминание"
        reminder_id = uuid.uuid4().hex[:8]
        task_name = f"MARKReminder_{reminder_id}"

    target_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
    clock = now if now is not None else datetime.now()
    if target_dt <= clock:
        return "Это время уже прошло."

    record = {
        "id": reminder_id,
        "date": date_str,
        "time": time_str,
        "message": message,
        "task_name": task_name,
        "os": backend,
    }
    if existing is not None:
        _unschedule(backend, existing, scheduler)
        items = [item for item in items if item["id"] != reminder_id]
    items.append(record)
    _save_store(path, items)

    scheduled = _schedule(backend, record, path, scheduler)
    if not _scheduler_ok(scheduled):
        _save_store(path, [item for item in items if item["id"] != reminder_id])
        if existing is not None:
            items_restored = _load_store(path)
            items_restored.append(existing)
            _save_store(path, items_restored)
        return "Не удалось запланировать напоминание из-за системной ошибки."

    _log(player, f"[reminder] set for {date_str} {time_str}")
    stamped = target_dt.strftime("%B %d at %I:%M %p")
    if replacing:
        return f"Reminder {reminder_id} updated for {stamped}."
    return f"Напоминание установлено на {stamped} (id: {reminder_id})."


def _schedule(
    backend: str,
    record: Mapping[str, str],
    store_path: Path,
    scheduler: Scheduler | None,
) -> Any:
    when = f"{record['date']}T{record['time']}"
    if backend == "windows":
        start = datetime.strptime(f"{record['date']} {record['time']}", "%Y-%m-%d %H:%M")
        xml_path = store_path.parent / f"{record['task_name']}.xml"
        arguments = " ".join(
            [
                str(Path(__file__).resolve()),
                "--notify",
                "--store",
                str(store_path),
                "--id",
                record["id"],
            ]
        )
        root = build_windows_task_xml(
            start=start,
            command=sys.executable,
            arguments=arguments,
            description=f"Slon Reminder {record['id']}",
        )
        write_windows_task_xml(xml_path, root)
        return _invoke(
            scheduler,
            ["schtasks", "/Create", "/TN", record["task_name"], "/XML", str(xml_path), "/F"],
        )
    if backend == "macos":
        return _invoke(
            scheduler,
            ["osascript", "--schedule", "--id", record["id"], "--store", str(store_path), "--when", when],
        )
    return _invoke(
        scheduler,
        [
            "at",
            "-t",
            datetime.strptime(when, "%Y-%m-%dT%H:%M").strftime("%Y%m%d%H%M"),
            "--id",
            record["id"],
            "--store",
            str(store_path),
        ],
    )


def _unschedule(
    backend: str,
    record: Mapping[str, str],
    scheduler: Scheduler | None,
) -> Any:
    if backend == "windows":
        return _invoke(scheduler, ["schtasks", "/Delete", "/TN", record["task_name"], "/F"])
    if backend == "macos":
        return _invoke(scheduler, ["osascript", "--cancel", "--id", record["id"]])
    return _invoke(scheduler, ["atrm", record["id"]])


def _invoke(scheduler: Scheduler | None, argv: list[str]) -> Any:
    if any(not isinstance(part, str) for part in argv):
        raise TypeError("scheduler argv must be a list of strings")
    if scheduler is not None:
        return scheduler(argv)
    return subprocess.run(argv, shell=False, capture_output=True, text=True)


def _scheduler_ok(result: Any) -> bool:
    if result is None:
        return True
    return getattr(result, "returncode", 0) == 0


def _load_store(store_path: Path) -> list[dict[str, str]]:
    if not store_path.is_file():
        return []
    try:
        payload = json.loads(store_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    items = payload.get("reminders") if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def _save_store(store_path: Path, items: list[Mapping[str, str]]) -> None:
    store_path.parent.mkdir(parents=True, exist_ok=True)
    store_path.write_text(
        json.dumps({"reminders": list(items)}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _require_id(parameters: Mapping[str, object]) -> str | None:
    value = parameters.get("id")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _optional_str(parameters: Mapping[str, object], key: str) -> str | None:
    value = parameters.get(key)
    if isinstance(value, str):
        return value
    return None


def _log(player: Any, message: str) -> None:
    if player is not None and hasattr(player, "write_log"):
        player.write_log(message)


def _notify_from_store(store_path: Path, reminder_id: str) -> str:
    """Read the JSON payload and return the stored message. No generated script."""
    for item in _load_store(store_path):
        if item.get("id") == reminder_id:
            return str(item.get("message") or "Напоминание")
    return "Напоминание"


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if "--notify" not in args:
        return 2
    store = None
    reminder_id = None
    for index, part in enumerate(args):
        if part == "--store" and index + 1 < len(args):
            store = args[index + 1]
        if part == "--id" and index + 1 < len(args):
            reminder_id = args[index + 1]
    if not store or not reminder_id:
        return 2
    print(_notify_from_store(Path(store), reminder_id))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
