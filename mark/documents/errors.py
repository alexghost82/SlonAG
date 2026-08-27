from i18n import t
"""Structured document-ingest error codes.

Messages must never include API keys, tokens, file payloads, or other secrets.
"""

from __future__ import annotations

CODE_OK = "ok"
CODE_TOO_LARGE = "too_large"
CODE_BAD_MIME = "bad_mime"
CODE_PATH_TRAVERSAL = "path_traversal"
CODE_ZIP_BOMB = "zip_bomb"
CODE_MISSING_HOOK = "missing_hook"

ERROR_CODES = frozenset(
    {
        CODE_OK,
        CODE_TOO_LARGE,
        CODE_BAD_MIME,
        CODE_PATH_TRAVERSAL,
        CODE_ZIP_BOMB,
        CODE_MISSING_HOOK,
    }
)

_MESSAGES: dict[str, str] = {
    CODE_OK: "Document ingest succeeded.",
    CODE_TOO_LARGE: "Document exceeds the configured size limit.",
    CODE_BAD_MIME: "Document type is not on the MIME or extension allow-list.",
    CODE_PATH_TRAVERSAL: "Document path escapes the injected root.",
    CODE_ZIP_BOMB: "Archive rejected as a zip bomb.",
    CODE_MISSING_HOOK: "Parser hook is not configured.",
}

_UNKNOWN = "Document ingest failed."


def document_message(code: str) -> str:
    """Return the explanation for a structured ingest error code."""
    return _MESSAGES.get(code, _UNKNOWN)


class DocumentIngestError(Exception):
    """Caller, guard, or configuration error during local document ingest."""

    def __init__(self, code: str, message: str | None = None) -> None:
        self.code = code
        super().__init__(message if message is not None else document_message(code))


class DocumentTooLargeError(DocumentIngestError):
    def __init__(self, message: str | None = None) -> None:
        super().__init__(CODE_TOO_LARGE, message)


class BadMimeError(DocumentIngestError):
    def __init__(self, message: str | None = None) -> None:
        super().__init__(CODE_BAD_MIME, message)


class PathTraversalError(DocumentIngestError):
    def __init__(self, message: str | None = None) -> None:
        super().__init__(CODE_PATH_TRAVERSAL, message)


class ZipBombError(DocumentIngestError):
    def __init__(self, message: str | None = None) -> None:
        super().__init__(CODE_ZIP_BOMB, message)


class MissingParserHookError(DocumentIngestError):
    def __init__(self, kind: str, message: str | None = None) -> None:
        self.kind = kind
        super().__init__(
            CODE_MISSING_HOOK,
            message if message is not None else f"parser hook for {kind} is not configured",
        )


__all__ = [
    "CODE_BAD_MIME",
    "CODE_MISSING_HOOK",
    "CODE_OK",
    "CODE_PATH_TRAVERSAL",
    "CODE_TOO_LARGE",
    "CODE_ZIP_BOMB",
    "ERROR_CODES",
    "BadMimeError",
    "DocumentIngestError",
    "DocumentTooLargeError",
    "MissingParserHookError",
    "PathTraversalError",
    "ZipBombError",
    "document_message",
]
