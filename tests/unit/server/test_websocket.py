"""Unit tests for in-process EventsHub (websocket mock)."""

from __future__ import annotations

import pytest

from server.routes._common import DevicePrincipal
from server.schemas import CODE_UNAUTHORIZED
from server.websocket import EventsHub, EventsUnauthorizedError


def test_websocket_rejects_unauthenticated_subscribe() -> None:
    hub = EventsHub()
    with pytest.raises(EventsUnauthorizedError) as exc_info:
        hub.subscribe(principal=None)
    assert exc_info.value.code == CODE_UNAUTHORIZED
    assert hub.subscriber_count == 0


def test_websocket_rejects_revoked_subscribe() -> None:
    hub = EventsHub()
    with pytest.raises(EventsUnauthorizedError):
        hub.subscribe(principal=DevicePrincipal(device_id="dev_x", revoked=True))
    assert hub.subscriber_count == 0


def test_websocket_subscribe_publish_poll() -> None:
    hub = EventsHub()
    sub = hub.subscribe(principal=DevicePrincipal(device_id="dev_ok"))
    assert hub.subscriber_count == 1

    delivered = hub.publish({"event": "task.updated", "task_id": "t1"})
    assert delivered == 1
    events = sub.poll()
    assert events == [{"event": "task.updated", "task_id": "t1"}]
    assert sub.poll() == []


def test_websocket_closed_subscription_skipped() -> None:
    hub = EventsHub()
    sub = hub.subscribe(principal=DevicePrincipal(device_id="dev_ok"))
    sub.close()
    delivered = hub.publish({"event": "noop"})
    assert delivered == 0
    assert hub.subscriber_count == 0
