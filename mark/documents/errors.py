"""Structured document-ingest error codes.

Messages must never include API keys, tokens, file payloads, or other secrets.
"""

from __future__ import annotations

from i18n import t
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
    CODE_OK: t("documents.ok"),
    CODE_TOO_LARGE: t("documents.too_large"),
    CODE_BAD_MIME: t("documents.bad_mime"),
    CODE_PATH_TRAVERSAL: t("documents.path_traversal"),
    CODE_ZIP_BOMB: t("documents.zip_bomb"),
    CODE_MISSING_HOOK: t("documents.missing_hook"),
}

_UNKNOWN = t("documents.failed")


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
