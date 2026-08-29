"""Observability module — component status + structured logging.

Exports:
- ComponentState constants: available, unavailable, degraded, etc.
- ComponentStatus dataclass
- ComponentRegistry for registration of status checkers
- check_all_components() for full system status
- get_logger() for structured logging
- track_latency() for latency tracking
- Recovery logging functions
"""

from observability.status import (
    ComponentState,
    ComponentStatus,
    ComponentRegistry,
    available,
    unavailable,
    degraded,
    misconfigured,
    disabled,
    create_registry,
    check_all_components,
    get_component_status,
    all_statuses,
)
from observability.logging import (
    get_logger,
    track_latency,
    set_correlation_id,
    set_session_id,
    set_tool_call_id,
    generate_correlation_id,
    generate_session_id,
    log_recovery_attempt,
    log_recovery_success,
    log_recovery_failed,
    log_tool_call,
    sanitize_for_log,
)

__all__ = [
    "ComponentState",
    "ComponentStatus",
    "ComponentRegistry",
    "available",
    "unavailable",
    "degraded",
    "misconfigured",
    "disabled",
    "create_registry",
    "check_all_components",
    "get_component_status",
    "all_statuses",
    "get_logger",
    "track_latency",
    "set_correlation_id",
    "set_session_id",
    "set_tool_call_id",
    "generate_correlation_id",
    "generate_session_id",
    "log_recovery_attempt",
    "log_recovery_success",
    "log_recovery_failed",
    "log_tool_call",
    "sanitize_for_log",
]
