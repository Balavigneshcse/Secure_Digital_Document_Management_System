"""Built-in placeholder AI: text extraction + keyword/regex classification. Used only when no AI service is
configured (and in tests). It has no scanned-image OCR, no embeddings and no summaries."""
from __future__ import annotations

import io
import re
import zipfile

from . import AIResult

ENGINE = "stub-rules-v2"

_KEYWORDS: dict[str, tuple[str, ...]] = {
    "fir": ("first information report", "fir no", "f.i.r", "information given by"),
    "charge_sheet": ("charge sheet", "chargesheet", "final report under section 173", "section 173"),
    "witness_statement": ("witness", "statement of", "section 161", "section 180", "deposition"),
    "forensic_report": ("forensic", "fsl", "dna", "fingerprint", "ballistic", "laboratory", "lab report"),
    "court_filing": ("petition", "bail application", "before the hon'ble", "court of the", "memo of parties"),
    "judgment": ("judgment", "convicted", "acquitted", "order sheet", "decreed"),
    "legal_notice": ("legal notice", "notice under", "hereby called upon"),
    "evidence_record": ("seizure memo", "exhibit", "chain of custody", "seized", "malkhana"),
    "investigation_record": ("case diary", "panchnama", "spot inspection", "site inspection", "investigation"),
    "police_report": ("police report", "general diary", "daily diary", "complaint"),
    "medical_report": ("medical examination", "medico-legal", "mlc", "injury report", "post-mortem", "postmortem"),
    "arrest_warrant": ("warrant of arrest", "arrest warrant", "non-bailable warrant", "you are hereby commanded"),
}

_DATE = re.compile(
    r"\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{2}-\d{2}|\d{1,2}(?:st|nd|rd|th)?\s+"
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?,?\s+\d{4})\b",
    re.I,
)
_SECTION = re.compile(
    r"\b(?:Section|Sec\.?|S\.)\s*(\d+[A-Z]?(?:\(\d+\))?)\s*(?:of\s+(?:the\s+)?)?"
    r"(IPC|BNS|CrPC|BNSS|NDPS|POCSO|IT Act|Evidence Act)?",
)
# Names and places never span a line break ([ \t] rather than \s).
_PERSON = re.compile(
    r"\b(?:Mr|Mrs|Ms|Smt|Shri|Sh|Dr|Inspector|SI|ASI|Constable)\.?[ \t]+([A-Z][a-z]+(?:[ \t]+[A-Z][a-z]+){0,2})"
)
_LOCATION = re.compile(
    r"\b(?:P\.?S\.?|Police Station|resident of|r/o|village|District)[ \t]+([A-Z][A-Za-z]+(?:[ \t]+[A-Z][A-Za-z]+){0,2})"
)


def _uniq(items) -> list[str]:
    seen, out = set(), []
    for i in items:
        i = i.strip()
        if i and i.lower() not in seen:
            seen.add(i.lower())
            out.append(i)
    return out


def _extract_pdf(data: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def _extract_docx(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        xml = z.read("word/document.xml").decode("utf-8", "ignore")
    xml = re.sub(r"</w:p>", "\n", xml)
    return re.sub(r"<[^>]+>", "", xml)


class StubAI:
    name = ENGINE

    def process(self, filename: str, content_type: str, data: bytes) -> AIResult:
        try:
            if content_type == "application/pdf":
                text = _extract_pdf(data)
            elif content_type.endswith("wordprocessingml.document"):
                text = _extract_docx(data)
            elif content_type.startswith("text/"):
                text = data.decode("utf-8", "replace")
            else:
                text = ""  # scanned images need the real AI service (Tesseract)
        except Exception:
            text = ""
        text = text.strip()

        hay = f"{filename}\n{text}".lower()
        scores = {t: sum(hay.count(k) for k in kws) for t, kws in _KEYWORDS.items()}
        best, score = max(scores.items(), key=lambda kv: kv[1])
        sections = [f"{m.group(1)} {m.group(2)}".strip() if m.group(2) else m.group(1) for m in _SECTION.finditer(text)]
        return AIResult(
            text=text, ocr_confidence=0.9 if text else 0.0, ocr_method="stub-text", pages=[1] if text else [],
            doc_type=best if score else "other", doc_confidence=min(0.95, 0.4 + 0.15 * score) if score else 0.0,
            tags=[t for t, s in sorted(scores.items(), key=lambda kv: -kv[1]) if s][:3],
            entities={
                "persons": _uniq(m.group(1) for m in _PERSON.finditer(text))[:25],
                "dates": _uniq(m.group(1) for m in _DATE.finditer(text))[:25],
                "locations": _uniq(m.group(1) for m in _LOCATION.finditer(text))[:25],
                "sections": _uniq(sections)[:25],
            },
            embedding=None, engine=ENGINE,
        )

    def embed(self, text: str) -> list[float] | None:
        return None

    def summarize(self, text: str) -> str | None:
        return None

    def summarize_case(self, documents: list[dict]) -> dict | None:
        return None
