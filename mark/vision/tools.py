"""Vision Runtime — tool registry for AgentLoop.

Provides Mark tools that the agent can call to interact with the
Vision Runtime: ``vision_capture``, ``vision_query``, ``vision_tracks``.
"""

from __future__ import annotations

import time
from typing import Any

from mark.tools.registry import ToolRegistry


def register_vision_tools(registry: ToolRegistry, runtime: Any) -> None:
    """Register vision-related tools with the Mark tool registry.

    Parameters
    ----------
    registry : ToolRegistry
        The Mark tool registry.
    runtime : VisionRuntime
        The Vision Runtime instance.
    """

    @registry.tool("vision_capture", "Capture a single frame from the vision source.")
    async def vision_capture() -> dict[str, Any]:
        """Capture one frame."""
        status = runtime.status()
        return {
            "running": status.is_running,
            "source": status.source_type,
            "frame_index": status.frame_count,
            "active_tracks": status.active_tracks,
            "timestamp": time.time(),
        }

    @registry.tool("vision_query", "Query the current vision state.")
    async def vision_query(query: str = "status") -> dict[str, Any]:
        """Query vision state.

        Parameters
        ----------
        query : str
            One of: "status", "tracks", "events", "detections".
        """
        status = runtime.status()
        if query == "status":
            return {
                "running": status.is_running,
                "source": status.source_type,
                "frame_count": status.frame_count,
                "active_tracks": status.active_tracks,
                "total_events": status.total_events,
                "errors": status.errors,
            }
        elif query == "tracks":
            return {
                "present": runtime.get_present_tracks(),
                "all": {tid: {
                    "label": ts.label,
                    "kind": ts.kind.value,
                    "age": ts.age,
                    "trajectory_len": len(ts.trajectory),
                    "present": ts.is_present,
                } for tid, ts in runtime.get_active_tracks().items()},
            }
        elif query == "events":
            events = await runtime.get_recent_events(20)
            return {
                "events": [
                    {"type": e.event_type.value, "track_id": e.track_id,
                     "description": e.description, "timestamp": e.timestamp}
                    for e in events
                ],
            }
        elif query == "detections":
            detections = await runtime.get_recent_detections(20)
            return {
                "detections": [
                    {
                        "kind": d.kind.value,
                        "label": d.label,
                        "confidence": d.confidence,
                        "bbox": {"x_min": d.bbox.x_min, "y_min": d.bbox.y_min,
                                 "x_max": d.bbox.x_max, "y_max": d.bbox.y_max},
                        "track_id": d.track_id,
                    }
                    for d in detections
                ],
            }
        return {"error": "unknown query"}

    @registry.tool("vision_tracks", "List current tracks and their trajectories.")
    async def vision_tracks(track_id: str | None = None) -> dict[str, Any]:
        """List tracks.

        Parameters
        ----------
        track_id : str, optional
            If given, return trajectory for that specific track.
        """
        if track_id:
            traj = runtime.get_trajectory(track_id)
            return {
                "track_id": track_id,
                "trajectory": [
                    {"frame_index": p.timestamp, "cx": p.center_x, "cy": p.center_y}
                    for p in traj
                ],
            }
        tracks = runtime.get_active_tracks()
        return {
            "track_count": len(tracks),
            "tracks": {
                tid: {"label": ts.label, "age": ts.age, "count": len(ts.trajectory)}
                for tid, ts in tracks.items()
            },
        }


def register_vision_capabilities(capabilities: dict[str, bool], runtime: Any) -> None:
    """Register vision capability flags with the Mark capabilities system."""
    caps = runtime.get_capabilities()
    capabilities["vision"] = True
    capabilities["vision_object_detection"] = caps.get("object_detection", False)
    capabilities["vision_person_detection"] = caps.get("person_detection", False)
    capabilities["vision_ocr"] = caps.get("ocr", False)
