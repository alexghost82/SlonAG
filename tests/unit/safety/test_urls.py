"""URL / SSRF helpers. No DNS, no sockets, no secrets in errors."""

from __future__ import annotations

import mark.safety.urls as urls_mod
import pytest

from mark.safety import CODE_UNSAFE_URL, UnsafeUrlError, check_url

SECRET = "sk-abcdefghijklmnopqrstuvwxyz012345"


def test_public_https_is_allowed() -> None:
    check_url("https://example.com")
    check_url("https://example.com/path?q=1")
    check_url("http://example.com")


@pytest.mark.parametrize(
    "url",
    (
        "file:///etc/passwd",
        "ftp://example.com/",
        "gopher://example.com/",
        "javascript:alert(1)",
        "http://127.0.0.1/",
        "http://127.0.0.1:8080/admin",
        "http://localhost/",
        "http://localhost.localdomain/",
        "http://[::1]/",
        "http://[::ffff:127.0.0.1]/",
        "http://0.0.0.0/",
        "http://10.0.0.1/",
        "http://192.168.1.1/",
        "http://172.16.0.1/",
        "http://169.254.1.1/",
        "http://169.254.169.254/",
        "http://169.254.169.254/latest/meta-data",
        "http://metadata.google.internal/",
        "http://metadata.google.internal/computeMetadata/v1/",
        "http://METADATA.GOOGLE.INTERNAL/",
        "http://x.metadata.google.internal/",
        "http://2130706433/",
        "http://0x7f000001/",
        "http://0177.0.0.1/",
        "not-a-url",
        "",
    ),
)
def test_ssrf_file_and_private_urls_are_rejected(url: str) -> None:
    with pytest.raises(UnsafeUrlError) as exc_info:
        check_url(url)
    assert exc_info.value.code == CODE_UNSAFE_URL


def test_unsafe_url_errors_do_not_echo_secrets() -> None:
    with pytest.raises(UnsafeUrlError) as exc_info:
        check_url(f"http://127.0.0.1/callback?api_key={SECRET}&token={SECRET}")
    message = str(exc_info.value)
    assert SECRET not in message
    assert "api_key" not in message
    assert "127.0.0.1" not in message


def test_url_checks_do_not_import_socket() -> None:
    assert "socket" not in urls_mod.__dict__
    assert "request" not in urls_mod.__dict__
