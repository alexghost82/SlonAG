from __future__ import annotations

from providers.errors import (
    CapabilityError,
    ProviderAuthError,
    ProviderError,
    ProviderOfflineError,
    redact_secrets,
)

KEY_LIKE = "sk-abcdefghijklmnopqrstuvwxyz012345"
GEMINI_LIKE = "AIzaSyDummyValueThatLooksLikeAKey99"
BEARER_LIKE = "Bearer tok_live_not_a_real_secret_value"


def test_provider_error_redacts_openai_style_key() -> None:
    error = ProviderAuthError(
        f"authentication failed for {KEY_LIKE}",
        provider_id="openai",
    )
    message = str(error)
    assert KEY_LIKE not in message
    assert "sk-abcdefghijklmnopqrstuvwxyz012345" not in repr(error)
    assert "[REDACTED]" in message
    assert error.provider_id == "openai"


def test_provider_error_redacts_gemini_style_key() -> None:
    error = ProviderError(f"upstream rejected {GEMINI_LIKE}", provider_id="gemini")
    assert GEMINI_LIKE not in str(error)
    assert GEMINI_LIKE not in repr(error)


def test_provider_error_redacts_assignment_and_bearer() -> None:
    assigned = ProviderOfflineError("offline api_key=super-secret-value-123")
    assert "super-secret-value-123" not in str(assigned)
    bearer = ProviderError(f"header {BEARER_LIKE}")
    assert "tok_live_not_a_real_secret_value" not in str(bearer)


def test_capability_error_message_has_no_key_like_values() -> None:
    error = CapabilityError(
        f"model demo cannot serve chat with key {KEY_LIKE}",
        provider_id="local",
        role="chat",
        model_id="demo",
    )
    assert KEY_LIKE not in str(error)
    assert error.role == "chat"
    assert error.model_id == "demo"


def test_redact_secrets_leaves_ordinary_text() -> None:
    text = "model demo-chat does not support role vision"
    assert redact_secrets(text) == text
