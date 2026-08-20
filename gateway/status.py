"""Read-only cross-process Gateway status projection for the desktop UI."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Mapping


def read_gateway_status(
    path: str | Path, *, stale_after_seconds: float = 5.0
) -> Mapping[str, object]:
    database = Path(path)
    if not database.is_file():
        return {"state": "disabled"}
    try:
        uri = f"file:{database.resolve()}?mode=ro"
        connection = sqlite3.connect(uri, uri=True)
        connection.row_factory = sqlite3.Row
        try:
            row = connection.execute(
                "SELECT * FROM gateway_runtime_status WHERE singleton=1"
            ).fetchone()
        finally:
            connection.close()
    except (sqlite3.Error, OSError):
        return {"state": "unavailable"}
    if row is None:
        return {"state": "stopped"}
    result = dict(row)
    if (str(result["state"]) in {"starting", "running", "degraded"}
            and time.time() - float(result["heartbeat_at"]) > stale_after_seconds):
        result["state"] = "unavailable"
    return result


__all__ = ["read_gateway_status"]
