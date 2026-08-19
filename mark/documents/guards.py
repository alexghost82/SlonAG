"""Size, MIME, path, and zip-bomb guards. Never extract archive payloads."""

from __future__ import annotations

import io
import mimetypes
import zipfile
from pathlib import Path

from mark.documents.errors import (
    BadMimeError,
    DocumentTooLargeError,
    PathTraversalError,
    ZipBombError,
)
from mark.documents.types import DocumentKind

DEFAULT_MAX_SIZE = 10 * 1024 * 1024
DEFAULT_MAX_ZIP_RATIO = 100.0
DEFAULT_MAX_ZIP_UNCOMPRESSED = 50 * 1024 * 1024
DEFAULT_MAX_ZIP_ENTRIES = 10_000

CODE_EXTENSIONS = frozenset(
    {
        ".c",
        ".cpp",
        ".cs",
        ".css",
        ".go",
        ".h",
        ".hpp",
        ".html",
        ".java",
        ".js",
        ".json",
        ".jsx",
        ".kt",
        ".lua",
        ".php",
        ".py",
        ".r",
        ".rb",
        ".rs",
        ".sh",
        ".sql",
        ".swift",
        ".toml",
        ".ts",
        ".tsx",
        ".yaml",
        ".yml",
    }
)

IMAGE_EXTENSIONS = frozenset({".bmp", ".gif", ".jpeg", ".jpg", ".png", ".webp"})
AUDIO_EXTENSIONS = frozenset({".aac", ".flac", ".m4a", ".mp3", ".ogg", ".opus", ".wav"})
VIDEO_EXTENSIONS = frozenset({".avi", ".m4v", ".mkv", ".mov", ".mp4", ".webm"})

EXTENSION_KINDS: dict[str, DocumentKind] = {
    ".txt": DocumentKind.TXT,
    ".log": DocumentKind.TXT,
    ".md": DocumentKind.MARKDOWN,
    ".markdown": DocumentKind.MARKDOWN,
    ".pdf": DocumentKind.PDF,
    ".docx": DocumentKind.DOCX,
}
EXTENSION_KINDS.update({ext: DocumentKind.CODE for ext in CODE_EXTENSIONS})
EXTENSION_KINDS.update({ext: DocumentKind.IMAGE for ext in IMAGE_EXTENSIONS})
EXTENSION_KINDS.update({ext: DocumentKind.AUDIO for ext in AUDIO_EXTENSIONS})
EXTENSION_KINDS.update({ext: DocumentKind.VIDEO for ext in VIDEO_EXTENSIONS})

ALLOWED_MIMES = frozenset(
    {
        "application/javascript",
        "application/json",
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "audio/aac",
        "audio/flac",
        "audio/m4a",
        "audio/mp4",
        "audio/mpeg",
        "audio/ogg",
        "audio/opus",
        "audio/wav",
        "audio/x-flac",
        "audio/x-m4a",
        "audio/x-wav",
        "image/bmp",
        "image/gif",
        "image/jpeg",
        "image/png",
        "image/webp",
        "text/css",
        "text/html",
        "text/javascript",
        "text/markdown",
        "text/plain",
        "text/x-python",
        "text/x-sh",
        "text/x-yaml",
        "text/xml",
        "video/mp4",
        "video/quicktime",
        "video/webm",
        "video/x-matroska",
        "video/x-msvideo",
    }
)

_NESTED_ZIP_SUFFIXES = frozenset({".zip", ".zipx"})


def resolve_under_root(path: Path, root: Path) -> Path:
    """Resolve ``path`` inside ``root`` or raise ``PathTraversalError``."""
    if ".." in path.parts or ".." in str(path):
        raise PathTraversalError()
    root_resolved = root.resolve()
    candidate = path if path.is_absolute() else root_resolved / path
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root_resolved)
    except ValueError:
        raise PathTraversalError() from None
    return resolved


def assert_max_size(size: int, max_size: int) -> None:
    if size > max_size:
        raise DocumentTooLargeError()


def looks_like_zip(data: bytes) -> bool:
    return len(data) >= 2 and data.startswith(b"PK")


def sniff_mime(data: bytes) -> str | None:
    """Return a MIME type from magic bytes, or None when unknown."""
    if data.startswith(b"%PDF"):
        return "application/pdf"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"GIF87a") or data.startswith(b"GIF89a"):
        return "image/gif"
    if data.startswith(b"BM"):
        return "image/bmp"
    if data.startswith(b"RIFF") and data[8:12] == b"WAVE":
        return "audio/wav"
    if data.startswith(b"RIFF") and data[8:12] == b"AVI ":
        return "video/x-msvideo"
    if data.startswith(b"ID3") or data[:2] in {b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"}:
        return "audio/mpeg"
    if len(data) >= 12 and data[4:8] == b"ftyp":
        brand = data[8:12]
        if brand in {b"M4A ", b"M4B ", b"mp4a"}:
            return "audio/mp4"
        return "video/mp4"
    if data.startswith(b"MZ"):
        return "application/x-dosexec"
    if looks_like_zip(data):
        return "application/zip"
    return None


def kind_for_path(path: Path) -> DocumentKind:
    suffix = path.suffix.lower()
    kind = EXTENSION_KINDS.get(suffix)
    if kind is None:
        raise BadMimeError()
    return kind


def assert_allowed_mime(data: bytes, path: Path, kind: DocumentKind) -> None:
    guessed, _ = mimetypes.guess_type(path.name)
    sniffed = sniff_mime(data)
    if sniffed == "application/zip" and kind is DocumentKind.DOCX:
        sniffed = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    for mime in (sniffed, guessed):
        if mime is None:
            continue
        if mime not in ALLOWED_MIMES:
            raise BadMimeError()


def assert_not_zip_bomb(
    data: bytes,
    *,
    max_ratio: float = DEFAULT_MAX_ZIP_RATIO,
    max_uncompressed: int = DEFAULT_MAX_ZIP_UNCOMPRESSED,
    max_entries: int = DEFAULT_MAX_ZIP_ENTRIES,
) -> None:
    """Reject nested or high-ratio zips using only the central directory."""
    if not looks_like_zip(data):
        return
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        return
    try:
        infos = archive.infolist()
        if len(infos) > max_entries:
            raise ZipBombError()
        total_uncompressed = 0
        for info in infos:
            name = info.filename.replace("\\", "/").rstrip("/").lower()
            if Path(name).suffix in _NESTED_ZIP_SUFFIXES:
                raise ZipBombError()
            uncompressed = info.file_size
            compressed = info.compress_size
            total_uncompressed += uncompressed
            if uncompressed > max_uncompressed:
                raise ZipBombError()
            if compressed > 0 and uncompressed / compressed > max_ratio:
                raise ZipBombError()
        if total_uncompressed > max_uncompressed:
            raise ZipBombError()
    finally:
        archive.close()


__all__ = [
    "ALLOWED_MIMES",
    "AUDIO_EXTENSIONS",
    "CODE_EXTENSIONS",
    "DEFAULT_MAX_SIZE",
    "DEFAULT_MAX_ZIP_ENTRIES",
    "DEFAULT_MAX_ZIP_RATIO",
    "DEFAULT_MAX_ZIP_UNCOMPRESSED",
    "EXTENSION_KINDS",
    "IMAGE_EXTENSIONS",
    "VIDEO_EXTENSIONS",
    "assert_allowed_mime",
    "assert_max_size",
    "assert_not_zip_bomb",
    "kind_for_path",
    "looks_like_zip",
    "resolve_under_root",
    "sniff_mime",
]
