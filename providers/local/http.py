"""Injectable HTTP transport used by local adapters.

Unit tests supply a fake. The default implementation uses stdlib urllib
and is never exercised by the mocked test suite.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


@dataclass
class TransportResponse:
    """Minimal HTTP result. ``lines`` is used for streamed bodies."""

    status_code: int
    body: str
    headers: dict[str, str] = field(default_factory=dict)
    lines: tuple[str, ...] | None = None

    def json(self) -> object:
        if not self.body:
            return {}
        return json.loads(self.body)

    def iter_lines(self) -> Iterator[str]:
        if self.lines is not None:
            yield from self.lines
        elif self.body:
            yield from self.body.splitlines()


class Transport(Protocol):
    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        json_body: object | None = None,
        stream: bool = False,
        timeout: float = 30.0,
    ) -> TransportResponse: ...


class StdlibTransport:
    """urllib-backed transport for real local runtimes."""

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        json_body: object | None = None,
        stream: bool = False,
        timeout: float = 30.0,
    ) -> TransportResponse:
        req_headers = dict(headers or {})
        data: bytes | None = None
        if json_body is not None:
            data = json.dumps(json_body).encode("utf-8")
            req_headers.setdefault("Content-Type", "application/json")
        request = Request(url, data=data, headers=req_headers, method=method)
        try:
            with urlopen(request, timeout=timeout) as response:
                raw = response.read()
                body = raw.decode("utf-8", errors="replace")
                header_map = {str(key): str(value) for key, value in response.headers.items()}
                lines = tuple(body.splitlines()) if stream else None
                return TransportResponse(
                    status_code=int(response.status),
                    body=body,
                    headers=header_map,
                    lines=lines,
                )
        except HTTPError as exc:
            raw = exc.read()
            body = raw.decode("utf-8", errors="replace")
            header_map = {str(key): str(value) for key, value in exc.headers.items()}
            return TransportResponse(
                status_code=int(exc.code),
                body=body,
                headers=header_map,
            )
        except URLError:
            raise
