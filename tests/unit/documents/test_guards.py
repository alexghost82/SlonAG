from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from acta.documents import (
    CODE_BAD_MIME,
    CODE_PATH_TRAVERSAL,
    CODE_TOO_LARGE,
    CODE_ZIP_BOMB,
    BadMimeError,
    DocumentIngestor,
    DocumentTooLargeError,
    PathTraversalError,
    ZipBombError,
)
from acta.documents.guards import assert_not_zip_bomb


def _write(root: Path, name: str, data: bytes | str) -> Path:
    path = root / name
    if isinstance(data, bytes):
        path.write_bytes(data)
    else:
        path.write_text(data, encoding="utf-8")
    return path


def test_size_limit_rejected(
    ingest_root: Path,
    ingest_temp: Path,
) -> None:
    ingestor = DocumentIngestor(root=ingest_root, temp_dir=ingest_temp, max_size=8)
    path = _write(ingest_root, "big.txt", "0123456789")

    with pytest.raises(DocumentTooLargeError) as exc_info:
        ingestor.ingest(path)

    assert exc_info.value.code == CODE_TOO_LARGE
    assert list(ingest_temp.iterdir()) == []


def test_size_limit_rejected_for_source_bytes(
    ingest_root: Path,
    ingest_temp: Path,
) -> None:
    ingestor = DocumentIngestor(root=ingest_root, temp_dir=ingest_temp, max_size=4)
    path = ingest_root / "tiny.txt"

    with pytest.raises(DocumentTooLargeError) as exc_info:
        ingestor.ingest(path, source_bytes=b"12345")

    assert exc_info.value.code == CODE_TOO_LARGE
    assert list(ingest_temp.iterdir()) == []


@pytest.mark.parametrize(
    "name",
    ("payload.exe", "payload.bin", "payload.dll", "payload.zip"),
)
def test_bad_mime_and_extension_rejected(
    ingest_root: Path,
    ingest_temp: Path,
    ingestor: DocumentIngestor,
    name: str,
) -> None:
    path = _write(ingest_root, name, b"MZ\x90\x00not-allowed")

    with pytest.raises(BadMimeError) as exc_info:
        ingestor.ingest(path)

    assert exc_info.value.code == CODE_BAD_MIME
    assert list(ingest_temp.iterdir()) == []


def test_executable_magic_rejected_even_with_txt_extension(
    ingest_root: Path,
    ingest_temp: Path,
    ingestor: DocumentIngestor,
) -> None:
    path = _write(ingest_root, "disguised.txt", b"MZ\x90\x00fake-pe")

    with pytest.raises(BadMimeError) as exc_info:
        ingestor.ingest(path)

    assert exc_info.value.code == CODE_BAD_MIME


@pytest.mark.parametrize(
    "unsafe",
    (
        Path("..") / "escape.txt",
        Path("sub") / ".." / ".." / "escape.txt",
        Path("/etc/passwd"),
    ),
)
def test_path_traversal_rejected(
    ingest_root: Path,
    ingest_temp: Path,
    ingestor: DocumentIngestor,
    unsafe: Path,
) -> None:
    with pytest.raises(PathTraversalError) as exc_info:
        ingestor.ingest(unsafe)

    assert exc_info.value.code == CODE_PATH_TRAVERSAL
    assert list(ingest_temp.iterdir()) == []


def test_absolute_path_outside_root_rejected(
    ingest_root: Path,
    ingest_temp: Path,
    tmp_path: Path,
    ingestor: DocumentIngestor,
) -> None:
    outsider = tmp_path / "outside.txt"
    outsider.write_text("nope", encoding="utf-8")

    with pytest.raises(PathTraversalError) as exc_info:
        ingestor.ingest(outsider)

    assert exc_info.value.code == CODE_PATH_TRAVERSAL


def test_nested_zip_bomb_rejected_without_extracting(
    ingest_root: Path,
    ingest_temp: Path,
    ingestor: DocumentIngestor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inner = io.BytesIO()
    with zipfile.ZipFile(inner, "w") as archive:
        archive.writestr("inner.txt", "nested")
    outer = io.BytesIO()
    with zipfile.ZipFile(outer, "w") as archive:
        archive.writestr("nested.zip", inner.getvalue())
    path = _write(ingest_root, "bomb.zip", outer.getvalue())

    def fail_extract(self: zipfile.ZipFile, *args: object, **kwargs: object) -> None:
        raise AssertionError("zip payload must not be extracted")

    def fail_read(self: zipfile.ZipFile, *args: object, **kwargs: object) -> bytes:
        raise AssertionError("zip payload must not be read")

    monkeypatch.setattr(zipfile.ZipFile, "extract", fail_extract)
    monkeypatch.setattr(zipfile.ZipFile, "extractall", fail_extract)
    monkeypatch.setattr(zipfile.ZipFile, "read", fail_read)

    with pytest.raises(ZipBombError) as exc_info:
        ingestor.ingest(path)

    assert exc_info.value.code == CODE_ZIP_BOMB
    assert list(ingest_temp.iterdir()) == []


def test_high_ratio_zip_bomb_rejected(
    ingest_root: Path,
    ingest_temp: Path,
    ingestor: DocumentIngestor,
) -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("zeros.bin", b"\x00" * 200_000)
    path = _write(ingest_root, "ratio.zip", buffer.getvalue())

    with pytest.raises(ZipBombError) as exc_info:
        ingestor.ingest(path)

    assert exc_info.value.code == CODE_ZIP_BOMB
    assert list(ingest_temp.iterdir()) == []


def test_zip_bomb_guard_uses_central_directory_only() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("nested.zip", b"PK\x03\x04unused")
    with pytest.raises(ZipBombError) as exc_info:
        assert_not_zip_bomb(buffer.getvalue())
    assert exc_info.value.code == CODE_ZIP_BOMB
