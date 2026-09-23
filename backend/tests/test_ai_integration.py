"""End-to-end tests with the REAL local AI service (Tesseract OCR, fine-tuned classifier, multilingual embeddings,
Ollama). Skipped automatically when the service isn't running (docker run ... sdms-ai, see ai/README.md).

They assert behaviour that should hold for any reasonable model version (e.g. "a scanned FIR titled FIRST INFORMATION
REPORT is filed as an FIR") - not exact confidences, which change every time the classifier is retrained.
"""
from __future__ import annotations

import pathlib

import httpx
import pytest

from app.ai.http_client import HttpAI

pytestmark = pytest.mark.ai
FIX = pathlib.Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def ai_health(base_settings):
    if not (base_settings.ai_service_url and base_settings.ai_service_key):
        pytest.skip("SDMS_AI_SERVICE_URL / SDMS_AI_SERVICE_KEY not configured")
    try:
        r = httpx.get(base_settings.ai_service_url.rstrip("/") + "/ai/health", timeout=5)
        r.raise_for_status()
    except httpx.HTTPError as exc:
        pytest.skip(f"AI service not running: {exc}")
    return r.json()


@pytest.fixture
def aiworld(world, base_settings, ai_health):
    world.app.state.ai = HttpAI(base_settings.ai_service_url, base_settings.ai_service_key, timeout=240)
    world.ai_health = ai_health
    return world


def _upload_file(w, case_id, path: pathlib.Path, title: str, user="officer1"):
    r = w.client.post(f"/api/cases/{case_id}/documents", headers=w.h(user), data={"title": title},
                      files={"file": (path.name, path.read_bytes(), "application/octet-stream")})
    assert r.status_code == 201, r.text
    return r.json()


def test_scanned_pdf_is_ocrd_classified_and_indexed(aiworld):
    doc = _upload_file(aiworld, aiworld.make_case()["id"], FIX / "fir_scanned.pdf", "Scanned FIR")   # image-only PDF
    v = doc["versions"][0]
    assert v["ocr_method"] == "tesseract_pdf" and v["language"] == "eng" and (v["ocr_confidence"] or 0) > 0.7
    assert doc["doc_type"] == "fir"                                        # the title is in the header zone
    ents = v["ai_entities"]
    assert {"Ramesh Kumar", "Suresh Verma"} <= set(ents["persons"])
    assert "379 IPC" in ents["sections"] and "Kotwali" in ents["locations"] and "Rs. 45,000" in ents["amounts"]
    assert "theft" in v["ai_tags"]                                          # offence tag derived from section 379
    assert v["ai_provider"].startswith("sentinel-ai")


def test_photographed_document_is_read_too(aiworld):
    doc = _upload_file(aiworld, aiworld.make_case()["id"], FIX / "fir_photo.png", "Photo of FIR")     # rotated + blurred
    v = doc["versions"][0]
    assert v["ocr_method"] == "tesseract_image" and doc["doc_type"] == "fir"
    assert "379 IPC" in v["ai_entities"]["sections"]


def test_ocr_text_of_a_scan_is_keyword_searchable_but_stays_encrypted(aiworld):
    doc = _upload_file(aiworld, aiworld.make_case()["id"], FIX / "fir_scanned.pdf", "Scanned FIR")
    h = aiworld.h("officer1")
    hit = aiworld.client.get("/api/search", headers=h, params={"q": "Kotwali"}).json()
    assert [d["document_id"] for d in hit["documents"]] == [doc["id"]] and "Kotwali" in hit["documents"][0]["snippet"]
    assert aiworld.client.get("/api/search", headers=aiworld.h("officer2"), params={"q": "Kotwali"}).json()["documents"] == []
    import json

    raw = aiworld.app.state.mongo.doc_meta.find_one({"document_id": doc["id"]})
    assert "kotwali" not in json.dumps(raw, default=str).lower()


def test_semantic_search_with_real_embeddings_respects_permissions(aiworld):
    c1, c2 = aiworld.make_case("officer1"), aiworld.make_case("officer2", title="Other case")
    up = lambda case, user, text, name: aiworld.upload(case["id"], user, data=text.encode(), name=name, title=name)  # noqa: E731
    theft = up(c1, "officer1", "FIR: a motorcycle was stolen from outside the complainant's house near the market at night.", "theft.txt")
    dna = up(c1, "officer1", "Forensic laboratory report. DNA profiling of blood samples matched the reference sample of the suspect.", "dna.txt")
    invoice = up(c1, "officer1", "Invoice for office stationery: paper reams, printer cartridges, total payable by bank transfer.", "invoice.txt")
    other = up(c2, "officer2", "FIR: another two-wheeler theft, a scooter was stolen from a parking lot.", "other_theft.txt")

    q = lambda user, text: aiworld.client.get("/api/search", headers=aiworld.h(user), params={"q": text, "semantic": "true"})  # noqa: E731
    r = q("officer1", "vehicle stolen at night")
    assert r.status_code == 200 and r.json()["mode"] == "semantic"
    ids = [d["document_id"] for d in r.json()["documents"]]
    assert ids and ids[0] == theft["id"]                                    # no word in common with "motorcycle", still found
    assert other["id"] not in ids                                          # someone else's case never leaks, however similar
    r = q("officer1", "genetic evidence match")
    assert [d["document_id"] for d in r.json()["documents"]][:1] == [dna["id"]]
    assert invoice["id"] not in [d["document_id"] for d in q("officer1", "genetic evidence match").json()["documents"]]
    assert [d["document_id"] for d in q("officer2", "vehicle stolen at night").json()["documents"]] == [other["id"]]


def test_hindi_text_is_handled(aiworld):
    text = "थाना कोतवाली में श्री रमेश कुमार ने शिकायत दी कि उनकी दुकान से चोरी हुई। धारा 379 भा.दं.सं. के अंतर्गत मामला दर्ज किया गया।"
    doc = aiworld.upload(aiworld.make_case()["id"], data=text.encode(), name="hindi.txt", title="Hindi complaint")
    v = doc["versions"][0]
    assert v["language"] == "hin" and "रमेश कुमार" in v["ai_entities"]["persons"] and "379 IPC" in v["ai_entities"]["sections"]
    assert aiworld.client.get("/api/search", headers=aiworld.h("officer1"), params={"q": "कोतवाली"}).json()["documents"]  # Indic words search too


def test_local_llm_summary_and_case_overview(aiworld):
    if not aiworld.ai_health["llm"].get("available"):
        pytest.skip("Ollama model not available")
    c = aiworld.make_case()
    doc = _upload_file(aiworld, c["id"], FIX / "fir_scanned.pdf", "Scanned FIR")
    h = aiworld.h("officer1")
    s = aiworld.client.post(f"/api/documents/{doc['id']}/versions/1/summary", headers=h)
    assert s.status_code == 200 and s.json()["available"] and len(s.json()["summary"].split()) >= 10
    summary = s.json()["summary"]
    assert any(w in summary.lower() for w in ("motorcycle", "scooter", "theft"))
    # Grounding: whatever the model wrote, a section number that is not in the document must never survive
    # (the fixture mentions only sections 154, 379 and 34).
    import re

    assert {int(n) for n in re.findall(r"(?i)\bsections?\s+(\d+)", summary)} <= {154, 379, 34}
    assert not re.findall(r"(?i)\bsections?\s+(?!154\b|379\b|34\b)\d+", summary)
    ov = aiworld.client.post(f"/api/cases/{c['id']}/summary", headers=h)
    assert ov.status_code == 200 and ov.json()["available"] and ov.json()["overall"]
