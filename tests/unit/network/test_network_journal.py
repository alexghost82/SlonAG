"""Journal entries stay free of secrets and credential-bearing URLs."""

from __future__ import annotations

from acta.network import NetworkMode, NetworkPolicy
from acta.network.journal import journal_has_secret, redact_secrets, safe_domain

SECRET = "sk-abcdefghijklmnopqrstuvwxyz012345"
TOKEN = "super-secret-token-value"


def test_journal_has_tool_domain_reason_no_secrets() -> None:
    allowlist = frozenset({"fetch"})
    policy = NetworkPolicy(mode=NetworkMode.TOOLS_ONLY, tool_allowlist=allowlist)
    policy.check_request(
        url=f"https://api.example.com/v1?api_key={SECRET}&token={TOKEN}",
        tool="fetch",
    )
    policy.check_request(
        url=f"https://evil.example/?Authorization=Bearer%20{SECRET}",
        tool="other",
    )

    entries = policy.activity()
    assert len(entries) >= 2
    latest = entries[-1]
    assert latest.tool == "other"
    assert latest.domain == "evil.example"
    assert latest.reason
    assert latest.allowed is False

    assert not journal_has_secret(entries, SECRET)
    assert not journal_has_secret(entries, TOKEN)
    assert not journal_has_secret(entries, "api_key=")
    for entry in entries:
        assert "?" not in entry.domain
        assert "Authorization" not in entry.domain
        assert SECRET not in entry.domain
        assert SECRET not in entry.reason


def test_recent_returns_newest_window() -> None:
    policy = NetworkPolicy(mode=NetworkMode.HYBRID)
    for host in ("a.example", "b.example", "c.example"):
        policy.check_request(url=f"https://{host}/")
    recent = policy.recent(2)
    assert [entry.domain for entry in recent] == ["b.example", "c.example"]


def test_safe_domain_strips_credentials_and_query() -> None:
    assert safe_domain(f"https://user:{SECRET}@api.example.com/path?token={TOKEN}") == (
        "api.example.com"
    )
    assert SECRET not in redact_secrets(f"Bearer {SECRET}")
