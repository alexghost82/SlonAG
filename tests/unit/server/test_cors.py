"""Unit tests for CORS enforcement — whitelist with default deny."""

from __future__ import annotations

from server.app import DesktopControlApp, MockResponse


def test_no_cors_when_no_origins_configured() -> None:
    """With no allowed origins, every response must carry no CORS header."""
    app = DesktopControlApp()
    response = app.handle("GET", "/v1/status", headers={"Authorization": "Bearer token"})
    assert response._cors_origin is None


def test_no_cors_when_origin_not_whitelisted() -> None:
    """Origin not in the whitelist must not receive CORS headers."""
    app = DesktopControlApp(cors_allowed_origins=["https://allowed.com"])
    response = app.handle("GET", "/v1/status", headers={
        "Authorization": "Bearer token",
        "origin": "https://attacker.com",
    })
    assert response._cors_origin is None


def test_cors_origin_set_when_whitelisted() -> None:
    """Whitelisted origin must appear in the response's CORS field."""
    app = DesktopControlApp(cors_allowed_origins=["https://allowed.com"])
    response = app.handle("GET", "/v1/status", headers={
        "Authorization": "Bearer token",
        "origin": "https://allowed.com",
    })
    assert response._cors_origin == "https://allowed.com"


def test_health_endpoint_has_cors_when_whitelisted() -> None:
    """Health endpoint must also carry CORS headers for allowed origins."""
    app = DesktopControlApp(cors_allowed_origins=["https://dashboard.local"])
    response = app.handle("GET", "/v1/health", headers={
        "origin": "https://dashboard.local",
    })
    assert response.status_code == 200
    assert response.body["status"] == "ok"
    assert response._cors_origin == "https://dashboard.local"


def test_health_endpoint_no_cors_for_unallowed_origin() -> None:
    app = DesktopControlApp(cors_allowed_origins=["https://dashboard.local"])
    response = app.handle("GET", "/v1/health", headers={
        "origin": "https://evil.com",
    })
    assert response.status_code == 200
    assert response._cors_origin is None


def test_multiple_whitelisted_origins() -> None:
    """Multiple origins can be whitelisted independently."""
    origins = ["https://a.com", "https://b.com", "https://c.com"]
    app = DesktopControlApp(cors_allowed_origins=origins)

    for origin in origins:
        response = app.handle("GET", "/v1/health", headers={"origin": origin})
        assert response._cors_origin == origin

    response = app.handle("GET", "/v1/health", headers={"origin": "https://none.com"})
    assert response._cors_origin is None


def test_cors_present_on_mutating_routes() -> None:
    """POST routes (pairing, chat, etc.) must also carry CORS headers."""
    app = DesktopControlApp(cors_allowed_origins=["https://app.local"])
    response = app.handle("POST", "/v1/pairing/start", body={
        "idempotency_key": "test-key",
    }, headers={"origin": "https://app.local"})
    assert response._cors_origin == "https://app.local"


def test_cors_header_on_unauthenticated_routes_when_whitelisted() -> None:
    """CORS headers should be present even when a route is authenticated
    and the caller is not (the origin still gets the CORS header so the
    browser can distinguish server errors from CORS errors)."""
    app = DesktopControlApp(cors_allowed_origins=["https://app.local"])
    response = app.handle("GET", "/v1/status", headers={
        "origin": "https://app.local",
    })
    assert response._cors_origin == "https://app.local"
    assert response.status_code == 401  # still 401, but CORS header present


def test_cors_empty_list_is_no_cors() -> None:
    """Explicit empty whitelist must not allow any origin."""
    app = DesktopControlApp(cors_allowed_origins=[])
    response = app.handle("GET", "/v1/status", headers={
        "Authorization": "Bearer token",
        "origin": "https://app.local",
    })
    assert response._cors_origin is None


def test_cors_case_sensitive_origin_match() -> None:
    """Origin matching is case-sensitive per HTTP specification."""
    app = DesktopControlApp(cors_allowed_origins=["https://App.Local"])
    response = app.handle("GET", "/v1/health", headers={
        "origin": "https://app.local",
    })
    assert response._cors_origin is None
