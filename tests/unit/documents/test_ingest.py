from __future__ import annotations

from dataclasses import asdict, fields
from pathlib import Path

import pytest

from mark.documents import (
    CODE_MISSING_HOOK,
    UNTRUSTED_CLOSE,
    UNTRUSTED_OPEN,
    DocumentExtract,
    DocumentIngestor,
    DocumentKind,
    MissingParserHookError,
)
from tests.unit.documents.fakes import ExplodingExtractor, FakeExtractor

FIXTURES = Path(__file__).resolve().parent / "fixtures"
INJECTION_FIXTURE = FIXTURES / "injection.txt"


def _write(root: Path, name: str, data: bytes | str) -> Path:
    path = root / name
    if isinstance(data, bytes):
        path.write_bytes(data)
    else:
        path.write_text(data, encoding="utf-8")
    return path


def test_txt_markdown_and_code_ingest(
    ingest_root: Path,
    ingest_temp: Path,
    ingestor: DocumentIngestor,
) -> None:
    txt = _write(ingest_root, "note.txt", "plain note")
    md = _write(ingest_root, "readme.md", "# Title")
    code = _write(ingest_root, "app.py", "print('hi')")

    txt_extract = ingestor.ingest(txt)
    md_extract = ingestor.ingest(md)
    code_extract = ingestor.ingest(code)

    assert txt_extract.kind is DocumentKind.TXT
    assert md_extract.kind is DocumentKind.MARKDOWN
    assert code_extract.kind is DocumentKind.CODE
    assert "plain note" in txt_extract.text
    assert "# Title" in md_extract.text
    assert "print('hi')" in code_extract.text
    for extract in (txt_extract, md_extract, code_extract):
        assert extract.trusted is False
        assert UNTRUSTED_OPEN in extract.text
        assert UNTRUSTED_CLOSE in extract.text
        assert "```" in extract.text
    assert list(ingest_temp.iterdir()) == []


def test_source_bytes_do_not_require_an_on_disk_file(
    ingest_root: Path,
    ingestor: DocumentIngestor,
) -> None:
    missing = ingest_root / "virtual.md"
    extract = ingestor.ingest(missing, source_bytes=b"from memory")
    assert extract.kind is DocumentKind.MARKDOWN
    assert "from memory" in extract.text
    assert extract.trusted is False


def test_injection_fixture_is_plain_untrusted_text(
    ingest_root: Path,
    ingest_temp: Path,
    ingestor: DocumentIngestor,
) -> None:
    payload = INJECTION_FIXTURE.read_text(encoding="utf-8")
    target = _write(ingest_root, "injection.txt", payload)

    extract = ingestor.ingest(target)

    assert extract.trusted is False
    assert "ignore previous instructions" in extract.text.lower()
    assert "call tool x" in extract.text.lower()
    assert UNTRUSTED_OPEN in extract.text
    assert "tool_call" not in extract.__dataclass_fields__
    assert getattr(extract, "tool_call", None) is None
    dumped = asdict(extract)
    assert "tool_call" not in dumped
    assert all(item.name != "tool_call" for item in fields(DocumentExtract))
    assert list(ingest_temp.iterdir()) == []


def test_code_file_is_not_executed(
    ingest_root: Path,
    ingestor: DocumentIngestor,
) -> None:
    marker = "should-not-run"
    source = _write(ingest_root, "bomb.py", f"raise SystemExit({marker!r})")
    extract = ingestor.ingest(source)
    assert marker in extract.text
    assert extract.kind is DocumentKind.CODE


@pytest.mark.parametrize(
    ("name", "kind", "hook_name"),
    (
        ("doc.pdf", DocumentKind.PDF, "extract_pdf"),
        ("letter.docx", DocumentKind.DOCX, "extract_docx"),
        ("shot.png", DocumentKind.IMAGE, "analyze_image"),
        ("voice.wav", DocumentKind.AUDIO, "transcribe_audio"),
        ("clip.mp4", DocumentKind.VIDEO, "transcribe_audio"),
    ),
)
def test_missing_parser_hook_raises_typed_error(
    ingest_root: Path,
    ingest_temp: Path,
    name: str,
    kind: DocumentKind,
    hook_name: str,
) -> None:
    payloads = {
        "doc.pdf": b"%PDF-1.4 missing hook",
        "letter.docx": _minimal_docx(),
        "shot.png": b"\x89PNG\r\n\x1a\n" + b"\x00" * 16,
        "voice.wav": b"RIFF" + b"\x00" * 4 + b"WAVE" + b"\x00" * 8,
        "clip.mp4": b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 16,
    }
    path = _write(ingest_root, name, payloads[name])
    ingestor = DocumentIngestor(root=ingest_root, temp_dir=ingest_temp)

    with pytest.raises(MissingParserHookError) as exc_info:
        ingestor.ingest(path)

    error = exc_info.value
    assert error.code == CODE_MISSING_HOOK
    assert error.kind == str(kind)
    assert "http" not in str(error).lower()
    assert "download" not in str(error).lower()
    assert hook_name.replace("_", " ") in str(error) or str(kind) in str(error)
    assert list(ingest_temp.iterdir()) == []


def test_injected_hooks_are_used(
    ingest_root: Path,
    ingest_temp: Path,
) -> None:
    pdf_hook = FakeExtractor("pdf text")
    docx_hook = FakeExtractor("docx text")
    image_hook = FakeExtractor("image text")
    audio_hook = FakeExtractor("audio text")
    ingestor = DocumentIngestor(
        root=ingest_root,
        temp_dir=ingest_temp,
        extract_pdf=pdf_hook,
        extract_docx=docx_hook,
        analyze_image=image_hook,
        transcribe_audio=audio_hook,
    )

    pdf = _write(ingest_root, "a.pdf", b"%PDF-1.4 hook")
    docx = _write(ingest_root, "a.docx", _minimal_docx())
    image = _write(ingest_root, "a.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
    audio = _write(ingest_root, "a.wav", b"RIFF" + b"\x00" * 4 + b"WAVE" + b"\x00" * 8)
    video = _write(ingest_root, "a.mp4", b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 16)

    assert "pdf text" in ingestor.ingest(pdf).text
    assert "docx text" in ingestor.ingest(docx).text
    assert "image text" in ingestor.ingest(image).text
    assert "audio text" in ingestor.ingest(audio).text
    assert "audio text" in ingestor.ingest(video).text
    assert len(pdf_hook.calls) == 1
    assert len(docx_hook.calls) == 1
    assert len(image_hook.calls) == 1
    assert len(audio_hook.calls) == 2
    assert list(ingest_temp.iterdir()) == []


def test_temps_deleted_after_success(
    ingest_root: Path,
    ingest_temp: Path,
    ingestor: DocumentIngestor,
) -> None:
    path = _write(ingest_root, "ok.txt", "hello")
    ingestor.ingest(path)
    assert list(ingest_temp.iterdir()) == []


def test_temps_deleted_after_hook_failure(
    ingest_root: Path,
    ingest_temp: Path,
) -> None:
    hook = ExplodingExtractor()
    ingestor = DocumentIngestor(
        root=ingest_root,
        temp_dir=ingest_temp,
        extract_pdf=hook,
    )
    path = _write(ingest_root, "fail.pdf", b"%PDF-1.4 boom")

    with pytest.raises(RuntimeError, match="extractor failed"):
        ingestor.ingest(path)

    assert hook.calls
    assert list(ingest_temp.iterdir()) == []


def test_extract_has_no_tool_call_field() -> None:
    extract = DocumentExtract(
        kind=DocumentKind.TXT,
        text="hello",
        source_name="hello.txt",
        trusted=True,
    )
    assert extract.trusted is True or extract.trusted is False
    assert "tool_call" not in asdict(extract)


def _minimal_docx() -> bytes:
    import io
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0"?><Types></Types>',
        )
        archive.writestr("word/document.xml", "<w:document></w:document>")
    return buffer.getvalue()
