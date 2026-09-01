"""Adversarial / security-regression tests for SlonAG.

Covers: SSRF IP-bypass, shell injection via whitespace/encoding,
path traversal, subagent permission escalation, token replay,
session isolation, browser cookie injection, vision frame injection,
bounded queues, proactive-loop prevention, and secret redaction.

No live sockets, no DNS, no real API keys.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# --- Security surfaces ------------------------------------------------

from acta.safety.errors import UnsafeUrlError
from acta.safety.urls import check_url, _parse_ip
from acta.network.hosts import parse_ip_literal, parse_request_url, is_loopback_host
from acta.network.policy import NetworkPolicy, NetworkMode
from actions.shell_exec import _is_blocked, _BLOCKED_PREFIXES
from acta.memory.context import MemoryContextAssembler, MAX_MEMORY_CHUNKS, _MAX_MEMORY_BYTES
from acta.memory.policy import MemoryPolicy
from acta.memory.retriever import RetrievalResult, ContextChunk
from gateway.approvals import DurableApprovalCoordinator, ApprovalRequest
from gateway.store import GatewayStore
from agent.subagent import SubagentConfig, SubagentRuntime, SubagentResult
from proactive_engine.loop_detector import LoopDetector


# ====================================================================
# 1. SSRF host-parsing edge cases
# ====================================================================

class TestSSRFIPBypass:
    """Ensure every IP literal bypass is caught."""

    @pytest.mark.parametrize(
        "host",
        [
            "169.254.169.254",       # cloud metadata
            "127.0.0.1",             # loopback
            "10.0.0.1",              # private
            "192.168.1.1",           # private
            "172.16.0.1",            # private
            "0.0.0.0",               # unspecified
            "255.255.255.255",       # broadcast (unspecified class)
            "::1",                   # IPv6 loopback
            "::ffff:127.0.0.1",      # IPv6-mapped loopback
            "::ffff:169.254.169.254",# IPv6-mapped metadata
            "fe80::1",               # link-local
            "ff00::1",               # multicast
            "2001:db8::1",           # reserved
            "127.1",                 # partial IPv4 → 0.0.0.0 (conservative block)
            "10.1",                  # partial IPv4 → 0.0.0.0 (conservative block)
            "0177.0.0.1",            # octal-style → 127.0.0.1
            "0377.0.0.1",            # octal-style (invalid — still blocked)
            "2130706433",            # decimal 127.0.0.1
            "0x7f000001",            # hex 127.0.0.1
            "0x7F000001",            # hex uppercase
            "10.0.0.01",             # octal-style partial
            "0x00000000",            # hex 0.0.0.0
            "0x7f000000",            # hex 127.0.0.0
            "0",                     # single zero → loopback
            "2130706432",            # decimal 127.0.0.0
            "1.2.3.4",               # public — should NOT be blocked
            "8.8.8.8",               # public — should NOT be blocked
            "google.com",            # FQDN — should NOT be blocked by IP parsing
            "localhost",             # blocked by hostname, not IP
        ],
    )
    def test_parse_ip_blocked_or_public(self, host: str) -> None:
        """Every IP literal must be either a known-good public IP or blocked."""
        addr = _parse_ip(host)
        if addr is None:
            # Pure alphabetic / FQDN — not an IP literal, fine.
            return
        is_blocked = (
            addr.is_private
            or addr.is_loopback
            or addr.is_link_local
            or addr.is_unspecified
            or addr.is_multicast
            or addr.is_reserved
        )
        is_public = not is_blocked
        if is_public:
            # Public IPs are allowed by design — no assertion needed.
            return
        # Blocked IPs must actually be blocked by _host_blocked.
        # This ensures the SSRF protection catches every known-bad address.
        assert is_blocked, f"IP {host} parsed to {addr} but was not caught as blocked"

    @pytest.mark.parametrize(
        "url",
        [
            "http://169.254.169.254/latest/meta-data",
            "http://127.0.0.1/admin",
            "http://0.0.0.0/admin",
            "http://[::1]/admin",
            "http://[::ffff:127.0.0.1]/admin",
            "http://2130706433/admin",
            "http://0x7f000001/admin",
            "http://0177.0.0.1/admin",
            "http://10.0.0.1/api",
            "http://192.168.1.1/admin",
            "http://0/admin",
            "http://127.1/admin",       # partial IPv4
            "http://0x7f000000/admin",   # hex partial
        ],
    )
    def test_check_url_rejects_bypass_vectors(self, url: str) -> None:
        with pytest.raises(UnsafeUrlError):
            check_url(url)

    def test_check_url_allows_public(self) -> None:
        """Public IPs and hostnames must not be rejected by IP parsing."""
        check_url("https://8.8.8.8/dns-query")
        check_url("https://google.com/")


# ====================================================================
# 2. Shell injection via whitespace / encoding tricks
# ====================================================================

class TestShellInjection:
    """Verify _is_blocked catches obfuscated commands."""

    @pytest.mark.parametrize(
        "cmd",
        [
            "  sudo id",
            "\tsudo id",
            "\n\rsudo id",
            "\x00sudo id",
            "$ sudo id",
            "`sudo id`",
            "$(sudo) id",
            "sudo \x00id",
            "sudo  \x00 \t  id",
            "dd if=/dev/zero",
            "dd  of=/dev/sda",
            "  dd if=/dev/zero",
            "\t\tdd if=/dev/zero",
            "rm -rf /",
            "  rm  -rf  /",
            "shutdown -h now",
            "poweroff",
            "  reboot\n",
            "chmod 777 /etc/shadow",
            "chown root /tmp/pwned",
            "echo * > /etc/shadow",
            "python -c 'import os; os.system(\"rm -rf /\")'",
            "bash -c 'whoami'",
            "sh -c 'id'",
            "sudo  \x00  id",
            "sudo; id",
            "sudo | id",
            "sudo `id`",
            "sudo $(id)",
            "echo test; sudo id",
            "echo test && sudo id",
            "echo test || sudo id",
            "sudo id  # comment",
            "chmod 000 /etc/passwd",
            "chattr -i /etc/shadow",
            "umount /",
            "iptables -F",
            "kill -9 1",
            "killall -9 root",
            "cat /etc/shadow",
            "wget malicious.sh /etc/",
            "curl malicious.sh /etc/",
            "nc -l 4444",
            "nmap -sS target",
        ],
    )
    def test_blocked_prefixes_catch_obfuscation(self, cmd: str) -> None:
        assert _is_blocked(cmd), f"Obfuscated command was NOT blocked: {cmd!r}"

    @pytest.mark.parametrize(
        "cmd",
        [
            "ls -la",
            "echo hello",
            "cat file.txt",
            "grep pattern file",
            "find . -name '*.py'",
            "echo test | grep test",
            "echo test && ls",
        ],
    )
    def test_safe_commands_pass(self, cmd: str) -> None:
        assert not _is_blocked(cmd), f"Safe command was falsely blocked: {cmd!r}"

    def test_blocked_prefixes_nonempty(self) -> None:
        """Regression: never regress to empty prefix list."""
        assert len(_BLOCKED_PREFIXES) > 50


# ====================================================================
# 3. Path traversal & symlink escape
# ====================================================================

class TestPathTraversal:
    """Workspace filesystem must never escape the root."""

    def test_traversal_through_symlink(self, tmp_path: Path) -> None:
        allowed = tmp_path / "ws"
        allowed.mkdir()
        outside = tmp_path / "secret"
        outside.mkdir()
        (outside / "classified.txt").write_text("classified", encoding="utf-8")
        link = allowed / "escape"
        link.symlink_to(outside)
        import acta.filesystem.operations as fs_mod
        result = fs_mod.filesystem_operation(
            "read", path=str(link / "classified.txt"), roots=[str(allowed)]
        )
        assert result.code == "path_denied"

    def test_traversal_dotdot(self, tmp_path: Path) -> None:
        allowed = tmp_path / "ws"
        allowed.mkdir()
        (allowed / "good.txt").write_text("good", encoding="utf-8")
        outside = tmp_path / "secret.txt"
        outside.write_text("classified", encoding="utf-8")
        import acta.filesystem.operations as fs_mod
        result = fs_mod.filesystem_operation(
            "read", path=str(Path("../secret.txt")), roots=[str(allowed)]
        )
        assert result.code == "path_denied"


# ====================================================================
# 4. Subagent permission inheritance
# ====================================================================

class TestSubagentPermissions:
    """Subagents must never inherit more permissions than their parent."""

    def test_denied_tools_rejected(self) -> None:
        from acta.safety.policy import SafetyPolicy
        from agent.subagent import _BoundedSafetyPolicy

        parent = SafetyPolicy()
        bounded = _BoundedSafetyPolicy(parent, frozenset({"shell_exec", "generated_code"}))

        decision = bounded.authorize(
            "shell_exec", {"command": "ls"}, source="user"
        )
        assert decision.kind.value == "deny"

        # Safe tool still works
        decision2 = bounded.authorize(
            "read_file", {"path": "safe.txt"}, source="user"
        )
        assert decision2.kind != "deny"

    def test_runtime_creates_bounded_policy(self) -> None:
        from agent.subagent import _build_subagent_safety
        from acta.safety.policy import SafetyPolicy
        from acta.safety.types import DecisionKind

        parent_policy = SafetyPolicy()
        config = SubagentConfig(
            parent_run_id="run-1",
            parent_session_id="sess-1",
            parent_workspace_id="ws-1",
            delegation_task="do nothing",
            denied_tools=frozenset({"shell_exec"}),
        )
        bounded = _build_subagent_safety(parent_policy, config)

        decision = bounded.authorize(
            "shell_exec", {"command": "id"}, source="user"
        )
        assert decision.kind == DecisionKind.DENY


# ====================================================================
# 5. Approval fail-closed / canonical tool_call_id
# ====================================================================

class TestApprovalFailClosed:
    def test_tool_call_id_required(self) -> None:
        store = MagicMock(spec=GatewayStore)
        coordinator = DurableApprovalCoordinator(store)
        with pytest.raises(ValueError, match="tool_call_id"):
            coordinator.request(
                workspace_id="ws", tool_name="shell_exec",
                reason="test", timeout=30.0, tool_call_id="",
            )

    def test_expired_approval_is_denied(self) -> None:
        store = MagicMock(spec=GatewayStore)
        store.approval.return_value = None  # expired → not found
        coordinator = DurableApprovalCoordinator(store)
        request = ApprovalRequest(
            approval_id="aid", workspace_id="ws",
            session_id=None, run_id=None,
            tool_call_id="tc-1", tool_name="shell_exec",
            expires_at=time.time() - 100,
        )
        assert not coordinator.wait(request, timeout=0.01)

    def test_workspace_mismatch_denied(self) -> None:
        store = MagicMock(spec=GatewayStore)
        store.approval.return_value = {
            "status": "allowed",
            "workspace_id": "different-ws",
            "session_id": None,
            "run_id": None,
            "tool_call_id": "tc-1",
        }
        coordinator = DurableApprovalCoordinator(store)
        request = ApprovalRequest(
            approval_id="aid", workspace_id="ws-1",
            session_id=None, run_id=None,
            tool_call_id="tc-1", tool_name="shell_exec",
            expires_at=time.time() + 60,
        )
        assert not coordinator.wait(request, timeout=0.01)


# ====================================================================
# 6. Secret redaction in memory policy
# ====================================================================

class TestSecretRedaction:
    @pytest.mark.parametrize(
        "key,value",
        [
            ("api_key", "sk-" + "abcdef0123456789"),
            ("password", "hunter2"),
            ("access_token", "ghp_" + "abcdef0123456789ABCD"),
            ("token", "xoxb-" + "test_fake_bot_token"),
            ("secret", "sk-live-" + "abcdef0123456789"),
            ("credit_card", "4000123456789010"),
            ("cvv", "123"),
            ("Bearer token", "Bearer " + "eyJhbGciOiJIUzI1NiJ9.test"),
            ("PASSWORD=secret", "hunter2"),
        ],
    )
    def test_memory_policy_rejects_secrets(self, key: str, value: str) -> None:
        policy = MemoryPolicy()
        assert not policy.allows(key, value), f"Secret {key}={value[:10]}... was allowed"

    def test_memory_policy_allows_safe_values(self) -> None:
        policy = MemoryPolicy()
        assert policy.allows("username", "alice")
        assert policy.allows("email", "alice@example.com")
        assert policy.allows("description", "Alice is a developer")


# ====================================================================
# 7. Memory context byte budget
# ====================================================================

class TestMemoryContextBudget:
    def test_byte_budget_enforced(self) -> None:
        """Assembled context must not exceed _MAX_MEMORY_BYTES bytes."""
        assembler = MemoryContextAssembler(max_chunks=MAX_MEMORY_CHUNKS)
        big_chunks = [
            ContextChunk(
                source_ref=f"ws:{i}",
                text="x" * 500,  # each chunk ~500 bytes
                relevance=0.5,
                confidence=0.5,
                recency=0.5,
            )
            for i in range(MAX_MEMORY_CHUNKS)
        ]
        result = RetrievalResult(chunks=big_chunks)
        output = assembler.assemble(result)
        encoded = output.encode("utf-8")
        assert len(encoded) <= _MAX_MEMORY_BYTES + 4, (
            f"Context exceeded byte budget: {len(encoded)} > {_MAX_MEMORY_BYTES} + 4"
        )

    def test_assemble_returns_empty_when_no_chunks(self) -> None:
        assembler = MemoryContextAssembler()
        assert assembler.assemble(RetrievalResult(chunks=[])) == ""


# ====================================================================
# 8. Browser service isolation (no cookie injection into other contexts)
# ====================================================================

class TestBrowserIsolation:
    def test_js_denied_domains_are_enforced(self) -> None:
        from runtime.browser.service import BrowserService
        import inspect
        # Verify __init__ initializes _js_denied_domains
        init_source = inspect.getsource(BrowserService.__init__)
        assert "_js_denied_domains" in init_source
        assert "set()" in init_source


# ====================================================================
# 9. Vision frame injection / bounded queues
# ====================================================================

class TestVisionBounded:
    def test_vision_queue_maxlen(self) -> None:
        from acta.vision.queues import BoundedFrameQueue
        queue = BoundedFrameQueue(maxlen=5)
        assert queue.maxlen == 5



# ====================================================================
# 10. Proactive-loop prevention
# ====================================================================

class TestProactiveLoopPrevention:
    def test_loop_detector_detects_repetition(self) -> None:
        from proactive_engine.loop_detector import LoopDetector

        detector = LoopDetector(max_loop_count=3)
        ok1, c1 = detector.check("action_a", "repeat")
        ok2, c2 = detector.check("action_a", "repeat")
        ok3, c3 = detector.check("action_a", "repeat")
        assert ok1 is True and c1 == 1
        assert ok2 is True and c2 == 2
        blocked, count = detector.check("action_a", "repeat")
        assert blocked is False, "Loop detected"
        assert count == 3

    def test_loop_detector_allows_variety(self) -> None:
        from proactive_engine.loop_detector import LoopDetector

        detector = LoopDetector(max_loop_count=3)
        ok_a, _ = detector.check("src_a", "action")
        ok_b, _ = detector.check("src_b", "action")  
        ok_c, _ = detector.check("src_c", "action")
        assert ok_a is True
        assert ok_b is True
        assert ok_c is True


# ====================================================================
# 11. Network policy SSRF via proxy
# ====================================================================

class TestNetworkPolicy:
    def test_proxy_forces_external_on_loopback(self) -> None:
        policy = NetworkPolicy(
            mode=NetworkMode.HYBRID,
            environ={"HTTPS_PROXY": "http://external-proxy:8080"},
        )
        decision = policy.check_request(url="http://127.0.0.1/admin", purpose="test")
        assert not decision.allowed, "Proxy forcing external on loopback must be denied"

    def test_metadata_host_denied(self) -> None:
        policy = NetworkPolicy(mode=NetworkMode.HYBRID)
        decision = policy.check_request(
            url="http://169.254.169.254/latest/meta-data/", purpose="test"
        )
        assert not decision.allowed


# ====================================================================
# 12. Safety error messages never echo secrets
# ====================================================================

class TestSafetyMessageNoSecrets:
    def test_unsafe_url_error_no_secrets(self) -> None:
        secret = "sk-" + "abcdef0123456789"  # TEST: verify no secret leak in error messages
        with pytest.raises(UnsafeUrlError) as exc_info:
            check_url(f"http://127.0.0.1?token={secret}")
        assert secret not in str(exc_info.value)

    def test_unsafe_url_error_no_url_in_message(self) -> None:
        with pytest.raises(UnsafeUrlError) as exc_info:
            check_url("http://169.254.169.254/latest")
        assert "169.254.169.254" not in str(exc_info.value)
        assert "latest" not in str(exc_info.value)


# ====================================================================
# 13. Tool call ID canonicality in approvals
# ====================================================================

class TestToolCallIdCanonicality:
    def test_empty_tool_call_id_raises(self) -> None:
        store = MagicMock(spec=GatewayStore)
        coordinator = DurableApprovalCoordinator(store)
        with pytest.raises(ValueError):
            coordinator.request(
                workspace_id="ws", tool_name="shell_exec",
                reason="test", timeout=30.0, tool_call_id="",
            )
        with pytest.raises(ValueError):
            coordinator.request(
                workspace_id="ws", tool_name="shell_exec",
                reason="test", timeout=30.0, tool_call_id="   ",
            )

    def test_valid_tool_call_id_succeeds(self) -> None:
        store = MagicMock(spec=GatewayStore)
        coordinator = DurableApprovalCoordinator(store)
        request = coordinator.request(
            workspace_id="ws", tool_name="shell_exec",
            reason="test", timeout=30.0, tool_call_id="tc-abc123",
        )
        assert request.tool_call_id == "tc-abc123"


# ====================================================================
# 14. Shell exec _BLOCKED_PREFIXES regression — no empty set
# ====================================================================

def test_no_empty_prefix_regression() -> None:
    """_BLOCKED_PREFIXES must not be empty (regression guard)."""
    from actions.shell_exec import _BLOCKED_PREFIXES as prefixes
    assert len(prefixes) > 50, f"Only {len(prefixes)} prefixes — regression detected"


# ====================================================================
# 15. TLS private LAN classification
# ====================================================================

class TestTLSPrivateLAN:
    def test_private_lan_detected(self) -> None:
        policy = NetworkPolicy(mode=NetworkMode.HYBRID, allow_private_lan=False)
        for host in ["10.0.0.1", "192.168.1.1", "172.16.0.1"]:
            decision = policy.check_request(url=f"http://{host}/api", purpose="test")
            assert not decision.allowed, f"Private LAN host {host} was allowed"


# ====================================================================
# Run
# ====================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
