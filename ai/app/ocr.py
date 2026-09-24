"""Text extraction: native text where the file has it, Tesseract (English + Hindi + Tamil) where it doesn't.

Adapted from the SentinelDMS_AI reference (PyMuPDF + Tesseract + langdetect). Changes: keeps line structure (the
entity extractor needs it), handles DOCX/TXT, enforces a page and time budget so one huge scan can't stall the
service, reads the Tesseract path from the environment instead of a hard-coded Windows path, and never lets a bad
page abort the whole document.
"""
from __future__ import annotations

import io
import logging
import os
import re
import time
import zipfile
from pathlib import Path

log = logging.getLogger("sentinel.ocr")

MAX_PAGES = int(os.getenv("OCR_MAX_PAGES", "60"))
TIME_BUDGET_S = float(os.getenv("OCR_TIME_BUDGET_S", "150"))
RENDER_DPI = int(os.getenv("OCR_DPI", "220"))
MAX_DOCX_XML_BYTES = int(os.getenv("OCR_MAX_DOCX_XML_MB", "20")) * 1024 * 1024  # a ZIP can inflate ~1000:1
LANG_MAP = {"en": "eng", "hi": "hin", "ta": "tam"}
DEFAULT_LANG = "eng+hin+tam"
NEEDS_REVIEW_BELOW = 0.55  # mean word confidence under which a human should look at the extraction
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}


def _tesseract():
    import pytesseract

    cmd = os.getenv("TESSERACT_CMD")
    if cmd:
        pytesseract.pytesseract.tesseract_cmd = cmd
    return pytesseract


def detect_language(text: str) -> str:
    """Tesseract language code for the dominant script of `text` (falls back to all three)."""
    try:
        from langdetect import DetectorFactory, detect

        DetectorFactory.seed = 0
        return LANG_MAP.get(detect(text.strip()[:3000]), DEFAULT_LANG)
    except Exception:
        return DEFAULT_LANG


def _prepare(image):
    """Grayscale + contrast + upscale small scans: cheap changes that reliably help Tesseract."""
    from PIL import Image, ImageOps

    img = image.convert("L")
    if img.width < 1600:
        f = 1600 / img.width
        img = img.resize((int(img.width * f), int(img.height * f)), Image.LANCZOS)
    return ImageOps.autocontrast(img)


def _image_to_text(image, lang: str) -> tuple[str, float]:
    """OCR one image. Returns (text with line breaks, mean word confidence 0-1)."""
    pt = _tesseract()
    data = pt.image_to_data(_prepare(image), lang=lang, output_type=pt.Output.DICT, config="--psm 3")
    lines: dict[tuple, list[str]] = {}
    confs: list[int] = []
    for w, c, b, p, l in zip(data["text"], data["conf"], data["block_num"], data["par_num"], data["line_num"]):
        try:
            c = int(float(c))
        except (TypeError, ValueError):
            continue
        if c > 0 and w.strip():
            lines.setdefault((b, p, l), []).append(w)
            confs.append(c)
    if not confs:
        return "", 0.0
    return "\n".join(" ".join(ws) for _, ws in sorted(lines.items())), round(sum(confs) / len(confs) / 100, 3)


def _ocr_image_bytes(data: bytes) -> dict:
    from PIL import Image

    img = Image.open(io.BytesIO(data))
    frames, texts, confs = [], [], []
    try:
        n = getattr(img, "n_frames", 1)
        for i in range(min(n, MAX_PAGES)):
            img.seek(i)
            frames.append(img.convert("RGB"))
    except EOFError:
        pass
    lang = DEFAULT_LANG
    for i, fr in enumerate(frames or [img.convert("RGB")], 1):
        t, c = _image_to_text(fr, lang)
        if i == 1 and t:
            lang = detect_language(t)
            if lang != DEFAULT_LANG:  # re-read with the specific model, usually cleaner
                t2, c2 = _image_to_text(fr, lang)
                if c2 >= c:
                    t, c = t2, c2
        if t.strip():
            texts.append(t)
            confs.append(c)
    return _result("\n\n".join(texts), confs, list(range(1, len(texts) + 1)), lang, "tesseract_image")


def _ocr_pdf_bytes(data: bytes) -> dict:
    import fitz  # PyMuPDF
    from PIL import Image

    doc = fitz.open(stream=data, filetype="pdf")
    parts, pages, confs = [], [], []
    lang, lang_known, scanned, truncated = DEFAULT_LANG, False, False, False
    start = time.monotonic()
    try:
        for n, page in enumerate(doc, 1):
            if n > MAX_PAGES or time.monotonic() - start > TIME_BUDGET_S:
                truncated = True
                break
            try:
                native = page.get_text().strip()
                if len(native) >= 20:
                    if not lang_known:
                        lang, lang_known = detect_language(native), True
                    parts.append(native), pages.append(n), confs.append(0.99)
                    continue
                scanned = True
                pix = page.get_pixmap(matrix=fitz.Matrix(RENDER_DPI / 72, RENDER_DPI / 72), alpha=False)
                img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                t, c = _image_to_text(img, lang)
                if not lang_known and t:
                    lang, lang_known = detect_language(t), True
                    if lang != DEFAULT_LANG:
                        t, c = _image_to_text(img, lang)
                if t.strip():
                    parts.append(t), pages.append(n), confs.append(c)
            except Exception:
                log.exception("page %s failed", n)
    finally:
        doc.close()
    method = ("tesseract_pdf" if scanned else "pymupdf_native") + ("+truncated" if truncated else "")
    return _result("\n\n".join(parts), confs, pages, lang, method, force_review=truncated)


def _docx(data: bytes) -> dict:
    with zipfile.ZipFile(io.BytesIO(data)) as z, z.open("word/document.xml") as f:
        raw = f.read(MAX_DOCX_XML_BYTES + 1)  # bounded: never trust the archive's own size fields
    if len(raw) > MAX_DOCX_XML_BYTES:
        raise ValueError("DOCX text is too large once decompressed")
    xml = raw.decode("utf-8", "ignore")
    text = re.sub(r"<[^>]+>", "", re.sub(r"</w:p>", "\n", xml)).strip()
    return _result(text, [0.99] if text else [], [1] if text else [], detect_language(text) if text else DEFAULT_LANG, "docx_native")


def _txt(data: bytes) -> dict:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = data.decode("latin-1")
    text = text.strip()
    return _result(text, [1.0] if text else [], [1] if text else [], detect_language(text) if text else DEFAULT_LANG, "text_native")


def _result(text: str, confs: list[float], pages: list[int], lang: str, method: str, force_review: bool = False) -> dict:
    conf = round(sum(confs) / len(confs), 3) if confs else 0.0
    return {
        "text": text.strip(), "confidence": conf, "language": lang, "pages": pages, "method": method,
        "needs_review": force_review or (0 < conf < NEEDS_REVIEW_BELOW) or (not text.strip()),
    }


def extract(data: bytes, filename: str) -> dict:
    """Routes by extension. Raises ValueError for unsupported types."""
    ext = Path(filename).suffix.lower()
    if ext == ".pdf":
        return _ocr_pdf_bytes(data)
    if ext in IMAGE_EXT:
        return _ocr_image_bytes(data)
    if ext == ".docx":
        return _docx(data)
    if ext in (".txt", ".text", ".md"):
        return _txt(data)
    raise ValueError(f"unsupported file type: {ext or 'unknown'}")
