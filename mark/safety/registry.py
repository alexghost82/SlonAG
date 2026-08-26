"""In-code tool risk and argument schemas. The model cannot write this table."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from mark.safety.errors import ArgValidationError, UnknownToolError
from mark.safety.types import RiskLevel

# Keys a model might send to lower the in-code risk. Ignored for policy.
OVERRIDE_KEYS = frozenset(
    {
        "authorized",
        "bypass",
        "confirmed",
        "decision",
        "kind",
        "level",
        "policy",
        "risk",
        "risk_level",
        "skip_confirm",
        "source",
    }
)

_ACTION_KEYS = ("action", "op")


@dataclass(frozen=True)
class ArgSchema:
    """Required keys and value types. Extra keys are allowed."""

    required: tuple[str, ...] = ()
    types: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class SafetyRule:
    """Conservative registry row. ``actions`` may lower or raise risk."""

    risk: RiskLevel
    deny: bool = False
    schema: ArgSchema = ArgSchema()
    actions: tuple[tuple[str, RiskLevel], ...] = ()


def _types(**fields: str) -> tuple[tuple[str, str], ...]:
    return tuple(fields.items())


_FILE_TYPES = _types(
    action="str",
    append="bool",
    content="str",
    count="int",
    destination="str",
    extension="str",
    max_results="int",
    name="str",
    new_name="str",
    path="str",
)

_DESKTOP_TYPES = _types(
    action="str",
    mode="str",
    op="str",
    path="str",
    task="str",
    url="str",
)

_REMINDER_TYPES = _types(
    action="str",
    date="str",
    id="str",
    message="str",
    op="str",
    time="str",
)

_REGISTRY: dict[str, SafetyRule] = {
    "read_file": SafetyRule(
        RiskLevel.READ,
        schema=ArgSchema(required=("path",), types=_types(path="str")),
    ),
    "web_search": SafetyRule(
        RiskLevel.READ,
        schema=ArgSchema(required=("query",), types=_types(query="str", mode="str")),
    ),
    "weather_report": SafetyRule(
        RiskLevel.READ,
        schema=ArgSchema(required=("city",), types=_types(city="str")),
    ),
    "flight_finder": SafetyRule(
        # Opens a browser and may persist results to Desktop.
        RiskLevel.CONFIRM,
        schema=ArgSchema(
            required=("origin", "destination", "date"),
            types=_types(
                cabin="str",
                date="str",
                destination="str",
                origin="str",
                passengers="int",
                return_date="str",
                save="bool",
            ),
        ),
    ),
    "youtube_video": SafetyRule(
        # Actions may open URLs or save generated summaries.
        RiskLevel.CONFIRM,
        schema=ArgSchema(
            types=_types(
                action="str",
                query="str",
                region="str",
                save="bool",
                url="str",
            ),
        ),
    ),
    "screen_process": SafetyRule(
        RiskLevel.NOTIFY,
        schema=ArgSchema(
            required=("text",),
            types=_types(angle="str", text="str"),
        ),
    ),
    "save_memory": SafetyRule(
        RiskLevel.NOTIFY,
        schema=ArgSchema(types=_types(key="str", value="str")),
    ),
    "file_processor": SafetyRule(
        # Many format-specific actions create derived files.
        RiskLevel.CONFIRM,
        schema=ArgSchema(
            types=_types(action="str", file_path="str", instruction="str"),
        ),
    ),
    "open_app": SafetyRule(
        RiskLevel.CONFIRM,
        schema=ArgSchema(required=("app_name",), types=_types(app_name="str")),
    ),
    "send_message": SafetyRule(
        RiskLevel.CONFIRM,
        schema=ArgSchema(
            required=("receiver", "message_text", "platform"),
            types=_types(
                message_text="str",
                platform="str",
                receiver="str",
            ),
        ),
    ),
    "browser_control": SafetyRule(
        RiskLevel.CONFIRM,
        schema=ArgSchema(
            required=("action",),
            types=_types(
                action="str",
                description="str",
                direction="str",
                incognito="bool",
                key="str",
                query="str",
                selector="str",
                text="str",
                url="str",
            ),
        ),
    ),
    "file_controller": SafetyRule(
        RiskLevel.CONFIRM,
        schema=ArgSchema(required=("action",), types=_FILE_TYPES),
        actions=(
            ("list", RiskLevel.READ),
            ("read", RiskLevel.READ),
            ("find", RiskLevel.READ),
            ("largest", RiskLevel.READ),
            ("disk_usage", RiskLevel.READ),
            ("info", RiskLevel.READ),
            ("copy", RiskLevel.CONFIRM),
            ("write", RiskLevel.CONFIRM),
            ("create_file", RiskLevel.CONFIRM),
            ("create_folder", RiskLevel.CONFIRM),
            ("organize_desktop", RiskLevel.CONFIRM),
            ("delete", RiskLevel.EXACT_CONFIRM),
            ("move", RiskLevel.EXACT_CONFIRM),
            ("rename", RiskLevel.EXACT_CONFIRM),
        ),
    ),
    "desktop_control": SafetyRule(
        RiskLevel.CONFIRM,
        schema=ArgSchema(types=_DESKTOP_TYPES),
        actions=(
            ("list", RiskLevel.READ),
            ("stats", RiskLevel.READ),
            ("current_wallpaper", RiskLevel.READ),
            ("screen.capture", RiskLevel.READ),
            ("wallpaper", RiskLevel.CONFIRM),
            ("wallpaper_url", RiskLevel.CONFIRM),
            ("organize", RiskLevel.CONFIRM),
            ("clean", RiskLevel.CONFIRM),
            ("mouse.click", RiskLevel.CONFIRM),
            ("keyboard.type", RiskLevel.CONFIRM),
            ("keyboard.shortcut", RiskLevel.CONFIRM),
            ("window.activate", RiskLevel.CONFIRM),
            ("file.copy", RiskLevel.CONFIRM),
        ),
    ),
    "reminder": SafetyRule(
        RiskLevel.CONFIRM,
        schema=ArgSchema(types=_REMINDER_TYPES),
        actions=(
            ("list", RiskLevel.READ),
            ("create", RiskLevel.CONFIRM),
            ("update", RiskLevel.CONFIRM),
            ("cancel", RiskLevel.CONFIRM),
        ),
    ),
    "computer_control": SafetyRule(
        RiskLevel.CONFIRM,
        schema=ArgSchema(
            required=("action",),
            types=_types(action="str", path="str", text="str"),
        ),
    ),
    "computer_settings": SafetyRule(
        RiskLevel.CONFIRM,
        schema=ArgSchema(
            types=_types(action="str", description="str", value="str"),
        ),
        actions=(
            ("shutdown", RiskLevel.BIOMETRIC),
            ("restart", RiskLevel.BIOMETRIC),
        ),
    ),
    "agent_task": SafetyRule(
        RiskLevel.CONFIRM,
        schema=ArgSchema(required=("goal",), types=_types(goal="str", priority="str")),
    ),
    "game_updater": SafetyRule(
        RiskLevel.EXACT_CONFIRM,
        schema=ArgSchema(
            types=_types(
                action="str",
                app_id="str",
                game_name="str",
                hour="int",
                minute="int",
                platform="str",
                shutdown_when_done="bool",
            ),
        ),
        actions=(
            ("list", RiskLevel.READ),
            ("download_status", RiskLevel.READ),
            ("schedule_status", RiskLevel.READ),
            ("install", RiskLevel.EXACT_CONFIRM),
            ("update", RiskLevel.EXACT_CONFIRM),
        ),
    ),
    "cmd_control": SafetyRule(
        RiskLevel.EXACT_CONFIRM,
        schema=ArgSchema(types=_types(command="str", cwd="str")),
    ),
    "shell_exec": SafetyRule(
        RiskLevel.EXACT_CONFIRM,
        schema=ArgSchema(
            required=("command",),
            types=_types(command="str", cwd="str", timeout="float", env_allowlist="list"),
        ),
    ),

    "code_helper": SafetyRule(
        RiskLevel.EXACT_CONFIRM,
        schema=ArgSchema(
            required=("action",),
            types=_types(
                action="str",
                args="str",
                code="str",
                description="str",
                file_path="str",
                language="str",
                output_path="str",
                timeout="int",
            ),
        ),
    ),
    "dev_agent": SafetyRule(
        RiskLevel.EXACT_CONFIRM,
        schema=ArgSchema(
            required=("description",),
            types=_types(
                description="str",
                language="str",
                project_name="str",
                timeout="int",
            ),
        ),
    ),
    "shutdown_slon": SafetyRule(RiskLevel.BIOMETRIC),
    "shutdown_jarvis": SafetyRule(RiskLevel.BIOMETRIC),
    "generated_code": SafetyRule(
        RiskLevel.BIOMETRIC,
        deny=True,
        schema=ArgSchema(
            required=("description",),
            types=_types(description="str"),
        ),
    ),
}


def registered_tools() -> frozenset[str]:
    """Return the frozen set of tool names the policy knows."""
    return frozenset(_REGISTRY)


def tool_spec(tool_name: str) -> SafetyRule:
    """Return the registry row or raise ``UnknownToolError``."""
    spec = _REGISTRY.get(tool_name)
    if spec is None:
        raise UnknownToolError(tool_name)
    return spec


def risk_for(tool_name: str) -> RiskLevel:
    """Return the conservative in-code risk. Arguments cannot change this."""
    return tool_spec(tool_name).risk


def action_name(args: Mapping[str, object]) -> str | None:
    """Return a normalized action/op string, ignoring policy-override keys."""
    for key in _ACTION_KEYS:
        if key in OVERRIDE_KEYS:
            continue
        value = args.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().lower()
    return None


def effective_risk(tool_name: str, args: Mapping[str, object]) -> RiskLevel:
    """Action-aware risk. Unknown actions keep the conservative registry value."""
    spec = tool_spec(tool_name)
    action = action_name(args)
    if action is None:
        return spec.risk
    for name, level in spec.actions:
        if name == action:
            return level
    return spec.risk


def _type_matches(value: object, expected: str) -> bool:
    if expected == "str":
        return isinstance(value, str)
    if expected == "bool":
        return isinstance(value, bool)
    if expected == "int":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "float":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "list":
        return isinstance(value, list)
    return False


def validate_args(tool_name: str, args: object) -> dict[str, object]:
    """Return a shallow copy of ``args`` after required-key and type checks."""
    spec = tool_spec(tool_name)
    if not isinstance(args, Mapping):
        raise ArgValidationError(tool_name, "Tool arguments must be a mapping.")
    checked = {str(key): value for key, value in args.items()}
    schema = spec.schema
    type_map = dict(schema.types)
    for key in schema.required:
        if key not in checked or checked[key] is None:
            raise ArgValidationError(
                tool_name,
                f"Missing required argument '{key}'.",
                field=key,
            )
    for key, value in checked.items():
        expected = type_map.get(key)
        if expected is None:
            continue
        if not _type_matches(value, expected):
            raise ArgValidationError(
                tool_name,
                f"Argument '{key}' has the wrong type.",
                field=key,
            )
    return checked


__all__ = [
    "OVERRIDE_KEYS",
    "ArgSchema",
    "SafetyRule",
    "action_name",
    "effective_risk",
    "registered_tools",
    "risk_for",
    "tool_spec",
    "validate_args",
]
