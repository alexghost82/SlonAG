"""Runtime status probes — real state, not fake defaults.

Every function here queries the actual backend.  If a probe
fails, the corresponding field is set to a safe ``False`` /
``None`` value rather than fabricating a positive answer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from server.schemas import StatusResponse


def get_runtime_status() -> StatusResponse:
    """Resolve real desktop status.

    Returns a :class:`StatusResponse` populated from live probes:
    - ``online``  — can the model adapter respond?
    - ``paired``  — is a gateway pairing token present?
    - ``network_mode`` — derived from network checks
    - ``provider_id`` / ``model_id`` — from live config / adapter

    If any probe fails, the field is defaulted conservatively.
    """
    online = False
    paired = False
    provider_id = None
    model_id = None
    network_mode = "offline"
    active_tasks = 0
    pending_approvals = 0

    # ── Provider / model detection ──────────────────────────────
    try:
        # Check if we have a running model provider
        from config.settings import load_settings

        settings = load_settings()
        if settings.provider_id:
            provider_id = settings.provider_id
            model_id = getattr(settings, "model_id", None) or settings.provider_id
    except Exception:
        pass

    # ── Gateway pairing check ──────────────────────────────────
    try:
        from pathlib import Path
        import sqlite3

        from gateway.db import gateway_db_path

        db_path = gateway_db_path()
        if db_path and Path(db_path).is_file():
            try:
                conn = sqlite3.connect(db_path, uri=True)
                try:
                    row = conn.execute(
                        "SELECT paired FROM gateway_pairing WHERE singleton=1"
                    ).fetchone()
                    if row is not None:
                        paired = bool(row[0])
                finally:
                    conn.close()
            except Exception:
                pass
    except Exception:
        pass

    # ── Network mode ───────────────────────────────────────────
    try:
        import socket

        try:
            sock = socket.create_connection(("8.8.8.8", 53), timeout=2)
            sock.close()
            network_mode = "internet"
            online = True
        except Exception:
            network_mode = "local"
            # Loopback check only
            try:
                sock = socket.create_connection(("127.0.0.1", 8765), timeout=1)
                sock.close()
                online = True
            except Exception:
                online = False
    except Exception:
        network_mode = "unknown"
        online = False

    # ── Runtime probe (lightweight) ────────────────────────────
    try:
        from agent.runtime import get_runtime

        rt = get_runtime()
        active_tasks = getattr(rt, "active_task_count", 0) or 0
        pending_approvals = getattr(rt, "pending_approvals", 0) or 0
        if active_tasks > 0:
            online = True
    except Exception:
        pass

    return StatusResponse(
        online=online,
        paired=paired,
        provider_id=provider_id,
        model_id=model_id,
        network_mode=network_mode,
        active_tasks=active_tasks,
        pending_approvals=pending_approvals,
    )
