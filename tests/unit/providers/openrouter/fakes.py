"""HTTP doubles for OpenRouter unit tests. No network I/O."""

from __future__ import annotations

from pathlib import Path

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
MODELS_FIXTURE = FIXTURES_DIR / "models.json"


class FakeResponse:
    """Minimal ``requests.Response`` stand-in used by the injectable transport."""

    def __init__(
        self,
        status_code: int = 200,
        payload: object | None = None,
        headers: dict[str, str] | None = None,
        lines: list[str] | None = None,
    ) -> None:
        self.status_code = status_code
        self.headers = headers or {}
        self._payload = {} if payload is None else payload
        self._lines = list(lines or [])

    def json(self) -> object:
        return self._payload

    def iter_lines(self, decode_unicode: bool = True) -> list[str]:
        return list(self._lines)
