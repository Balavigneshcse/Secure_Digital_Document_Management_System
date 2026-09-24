from __future__ import annotations

import io
import zipfile

import pytest

from app import ocr


def _docx(document_xml: bytes) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("word/document.xml", document_xml)
    return buf.getvalue()


def test_docx_text_is_read_with_a_hard_size_limit(monkeypatch):
    monkeypatch.setattr(ocr, "MAX_DOCX_XML_BYTES", 1024)
    assert "FIR No. 12" in ocr.extract(_docx(b"<w:p>FIR No. 12</w:p>"), "fir.docx")["text"]
    with pytest.raises(ValueError, match="too large"):  # a decompression bomb stops at the limit, not at the RAM limit
        ocr.extract(_docx(b"A" * 50_000), "bomb.docx")
