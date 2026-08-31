"""Local document ingest. Parsers and STT are injected; nothing is executed."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Callable
from pathlib import Path

from acta.documents.errors import MissingParserHookError
from acta.documents.guards import (
    DEFAULT_MAX_SIZE,
    DEFAULT_MAX_ZIP_RATIO,
    DEFAULT_MAX_ZIP_UNCOMPRESSED,
    assert_allowed_mime,
    assert_max_size,
    assert_not_zip_bomb,
    kind_for_path,
    resolve_under_root,
)
from acta.documents.types import DocumentExtract, DocumentKind, wrap_untrusted

ExtractPdfHook = Callable[[bytes], str]
ExtractDocxHook = Callable[[bytes], str]
AnalyzeImageHook = Callable[[bytes], str]
TranscribeAudioHook = Callable[[bytes], str]

_TEXT_KINDS = frozenset({DocumentKind.TXT, DocumentKind.MARKDOWN, DocumentKind.CODE})


class DocumentIngestor:
    """Ingest a local file with size, path, MIME, and zip-bomb guards."""

    def __init__(
        self,
        *,
        root: Path,
        temp_dir: Path,
        max_size: int = DEFAULT_MAX_SIZE,
        extract_pdf: ExtractPdfHook | None = None,
        extract_docx: ExtractDocxHook | None = None,
        analyze_image: AnalyzeImageHook | None = None,
        transcribe_audio: TranscribeAudioHook | None = None,
        max_zip_ratio: float = DEFAULT_MAX_ZIP_RATIO,
        max_zip_uncompressed: int | None = None,
    ) -> None:
        self.root = root
        self.temp_dir = temp_dir
        self.max_size = max_size
        self.extract_pdf = extract_pdf
        self.extract_docx = extract_docx
        self.analyze_image = analyze_image
        self.transcribe_audio = transcribe_audio
        self.max_zip_ratio = max_zip_ratio
        self.max_zip_uncompressed = (
            max_zip_uncompressed
            if max_zip_uncompressed is not None
            else DEFAULT_MAX_ZIP_UNCOMPRESSED
        )

    def ingest(self, path: Path, *, source_bytes: bytes | None = None) -> DocumentExtract:
        resolved = resolve_under_root(path, self.root)
        data = self._load_bytes(resolved, source_bytes)
        assert_max_size(len(data), self.max_size)
        assert_not_zip_bomb(
            data,
            max_ratio=self.max_zip_ratio,
            max_uncompressed=self.max_zip_uncompressed,
        )
        kind = kind_for_path(resolved)
        assert_allowed_mime(data, resolved, kind)
        temp_path = self._write_temp(data, resolved.suffix)
        try:
            raw_text = self._extract(kind, data)
            return DocumentExtract(
                kind=kind,
                text=wrap_untrusted(raw_text, kind),
                source_name=resolved.name,
                trusted=False,
            )
        finally:
            temp_path.unlink(missing_ok=True)

    def _load_bytes(self, resolved: Path, source_bytes: bytes | None) -> bytes:
        if source_bytes is not None:
            assert_max_size(len(source_bytes), self.max_size)
            return source_bytes
        assert_max_size(resolved.stat().st_size, self.max_size)
        data = resolved.read_bytes()
        assert_max_size(len(data), self.max_size)
        return data

    def _write_temp(self, data: bytes, suffix: str) -> Path:
        temp_root = self.temp_dir.resolve()
        temp_root.mkdir(parents=True, exist_ok=True)
        handle, raw_name = tempfile.mkstemp(
            prefix="mark-doc-",
            suffix=suffix,
            dir=str(temp_root),
        )
        temp_path = Path(raw_name)
        try:
            try:
                os.write(handle, data)
            finally:
                os.close(handle)
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise
        return temp_path

    def _extract(self, kind: DocumentKind, data: bytes) -> str:
        if kind in _TEXT_KINDS:
            return data.decode("utf-8", errors="replace")
        hook = self._hook_for(kind)
        if hook is None:
            raise MissingParserHookError(str(kind))
        return hook(data)

    def _hook_for(self, kind: DocumentKind) -> Callable[[bytes], str] | None:
        if kind is DocumentKind.PDF:
            return self.extract_pdf
        if kind is DocumentKind.DOCX:
            return self.extract_docx
        if kind is DocumentKind.IMAGE:
            return self.analyze_image
        if kind in {DocumentKind.AUDIO, DocumentKind.VIDEO}:
            return self.transcribe_audio
        return None


__all__ = [
    "AnalyzeImageHook",
    "DocumentIngestor",
    "ExtractDocxHook",
    "ExtractPdfHook",
    "TranscribeAudioHook",
]
