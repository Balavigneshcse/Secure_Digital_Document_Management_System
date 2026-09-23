from __future__ import annotations

import concurrent.futures as cf
import hashlib
import json

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app import docstore
from app.ai import AIResult, AIServiceError
from app.ai.http_client import HttpAI
from app.doc_service import commit_or_compensate
from app.models import Document, DocumentVersion
from conftest import FIR_TEXT


def _version(world, doc_id, no=1) -> DocumentVersion:
    with world.app.state.session_factory() as db:
        return db.execute(select(DocumentVersion).where(
            DocumentVersion.document_id == doc_id, DocumentVersion.version_no == no)).scalar_one()


def test_upload_hashes_encrypts_anchors_and_verifies(world):
    case = world.make_case()
    doc = world.upload(case["id"])
    v = doc["versions"][0]

    assert v["sha256"] == hashlib.sha256(FIR_TEXT).hexdigest()
    assert v["ledger_tx_id"] and v["ledger_block"] >= 1

    # Ledger holds the hash + minimal metadata, never the document.
    block = world.client.get(f"/api/ledger/tx/{v['ledger_tx_id']}", headers=world.h("auditor1")).json()
    assert block["kind"] == "DOC_VERSION"
    assert block["payload"]["sha256"] == v["sha256"] and block["payload"]["document_id"] == doc["id"]
    assert block["payload"]["document_uid"] == doc["uid"] and len(doc["uid"]) == 32
    assert "Ramesh" not in json.dumps(block)

    # At rest (GridFS): ciphertext, not the plaintext.
    row = _version(world, doc["id"])
    stored = world.app.state.storage.get(row.storage_key)
    assert b"FIRST INFORMATION REPORT" not in stored and len(stored) > len(FIR_TEXT)

    r = world.client.get(f"/api/documents/{doc['id']}/versions/1/verify", headers=world.h("officer1"))
    assert r.json()["status"] == "verified" and r.json()["reasons"] == []

    d = world.client.get(f"/api/documents/{doc['id']}/versions/1/download", headers=world.h("officer1"))
    assert d.status_code == 200 and d.content == FIR_TEXT
    assert d.headers["x-content-sha256"] == v["sha256"]
    assert "attachment" in d.headers["content-disposition"]


def test_document_text_and_entities_are_encrypted_in_mongodb(world):
    """The database must not hold searchable plaintext: only sealed content + keyed blind-index tokens."""
    doc = world.upload(world.make_case()["id"])
    raw = world.app.state.mongo.doc_meta.find_one({"_id": docstore.meta_key(doc["id"], 1)})
    dump = json.dumps(raw, default=str).lower()
    # Long words can't occur by chance inside base64 ciphertext / hex tokens, so they must not appear anywhere.
    for secret in ("ramesh", "suresh", "verma", "kotwali", "first information report"):
        assert secret not in dump, f"{secret!r} leaked into MongoDB in clear"
    # Short strings (like a section number) can match randomly inside ciphertext, so check only the cleartext fields.
    skip = ("content_enc", "kw", "embedding", "uploaded_at")  # ciphertext/tokens, and a timestamp whose digits can match anything
    clear = json.dumps({k: v for k, v in raw.items() if k not in skip}, default=str).lower()
    assert "379" not in clear and "ipc" not in clear
    assert raw["content_enc"] and len(raw["kw"]) > 5
    # ... but it round-trips for an authorised reader
    d = world.client.get(f"/api/documents/{doc['id']}", headers=world.h("officer1")).json()
    assert "Ramesh Kumar" in d["versions"][0]["ai_entities"]["persons"]
    # sealed content is bound to its record key: moving it to another record fails to decrypt
    from cryptography.exceptions import InvalidTag
    from app.crypto import open_json

    with pytest.raises(InvalidTag):
        open_json(world.app.state.kek, raw["content_enc"], b"999:1")


def test_ai_stub_classifies_and_extracts_entities(world):
    doc = world.upload(world.make_case()["id"])
    v = doc["versions"][0]
    assert doc["doc_type"] == "fir" and v["ai_doc_type"] == "fir"
    assert "Ramesh Kumar" in v["ai_entities"]["persons"]
    assert any("379" in s for s in v["ai_entities"]["sections"])
    assert "12/03/2026" in v["ai_entities"]["dates"]
    # A place name must not swallow the first word of the next line ("Kotwali\nDate of report").
    assert "Kotwali" in v["ai_entities"]["locations"]
    assert not any("Date" in loc for loc in v["ai_entities"]["locations"])
    assert v["ai_provider"] == "stub-rules-v2"


def test_explicit_doc_type_wins_over_ai_suggestion(world):
    doc = world.upload(world.make_case()["id"], doc_type="evidence_record")
    assert doc["doc_type"] == "evidence_record" and doc["versions"][0]["ai_doc_type"] == "fir"
    r = world.client.post(f"/api/cases/{doc['case_id']}/documents", headers=world.h("officer1"),
                          data={"title": "t", "doc_type": "nonsense"}, files={"file": ("a.txt", b"x", "text/plain")})
    assert r.status_code == 422


def test_new_version_keeps_history(world):
    case = world.make_case()
    doc = world.upload(case["id"])
    v2_bytes = FIR_TEXT + b"\nSupplementary: recovered item on 14/03/2026.\n"
    r = world.client.post(f"/api/documents/{doc['id']}/versions", headers=world.h("officer1"),
                          data={"change_note": "supplementary statement"},
                          files={"file": ("fir_v2.txt", v2_bytes, "text/plain")})
    assert r.status_code == 201
    out = r.json()
    assert out["current_version"] == 2 and [v["version_no"] for v in out["versions"]] == [1, 2]
    assert out["versions"][1]["change_note"] == "supplementary statement"

    h = world.h("officer1")
    assert world.client.get(f"/api/documents/{doc['id']}/versions/1/download", headers=h).content == FIR_TEXT
    assert world.client.get(f"/api/documents/{doc['id']}/versions/2/download", headers=h).content == v2_bytes

    # Ledger links each version to the hash of the previous one.
    b2 = world.client.get(f"/api/ledger/tx/{out['versions'][1]['ledger_tx_id']}", headers=world.h("auditor1")).json()
    assert b2["payload"]["prev_sha256"] == out["versions"][0]["sha256"] and b2["payload"]["version_no"] == 2


def test_concurrent_version_uploads_get_distinct_numbers(world):
    doc = world.upload(world.make_case()["id"])
    h = world.h("officer1")

    def up(i):
        return world.client.post(f"/api/documents/{doc['id']}/versions", headers=h,
                                 files={"file": (f"v{i}.txt", f"revision {i}".encode(), "text/plain")}).status_code

    with cf.ThreadPoolExecutor(6) as ex:
        codes = list(ex.map(up, range(6)))
    assert codes == [201] * 6
    final = world.client.get(f"/api/documents/{doc['id']}", headers=h).json()
    assert [v["version_no"] for v in final["versions"]] == list(range(1, 8))
    assert world.client.get("/api/audit/verify", headers=world.h("auditor1")).json()["ok"] is True


def test_upload_validation(world):
    cid = world.make_case()["id"]
    world.upload(cid, data=b"MZ\x90\x00", name="evil.exe", expect=415)
    world.upload(cid, data=b"just text pretending", name="fake.pdf", expect=415)
    world.upload(cid, data=b"", name="empty.txt", expect=400)
    world.upload(cid, data=b"bin\x00ary", name="bin.txt", expect=415)
    world.upload(cid, data=b"%PDF-1.4\n%%EOF", name="ok.pdf")  # magic bytes match -> accepted
    # Path components in the name are stripped, never used for storage.
    doc = world.upload(cid, data=b"hello", name="../../etc/passwd.txt")
    assert doc["versions"][0]["filename"] == "passwd.txt"
    # rejected uploads left no half-created documents behind
    with world.app.state.session_factory() as db:
        assert db.scalar(select(func.count(Document.id))) == 2


def test_upload_size_limit(world):
    world.app.state.settings.max_upload_mb = 1
    world.upload(world.make_case()["id"], data=b"a" * (1024 * 1024 + 1), name="big.txt", expect=413)


# ---- tamper detection --------------------------------------------------------------------------
def _assert_blocked_and_flagged(world, doc_id):
    r = world.client.get(f"/api/documents/{doc_id}/versions/1/download", headers=world.h("officer1"))
    assert r.status_code == 409
    assert r.json()["detail"]["report"]["status"] == "tampered"
    alerts = world.audit_actions(action="TAMPER_DETECTED")
    assert alerts and alerts[0]["outcome"] == "alert" and alerts[0]["detail"]["reasons"]
    return r.json()["detail"]["report"]


def test_modified_stored_file_is_detected_and_download_blocked(world):
    doc = world.upload(world.make_case()["id"])
    key = _version(world, doc["id"]).storage_key
    storage = world.app.state.storage
    raw = bytearray(storage.get(key))
    raw[-1] ^= 0x01
    storage.put(key, bytes(raw))

    report = _assert_blocked_and_flagged(world, doc["id"])
    assert any("decryption" in r for r in report["reasons"])
    # Auditor can independently confirm without seeing content.
    r = world.client.get(f"/api/documents/{doc['id']}/versions/1/verify", headers=world.h("auditor1"))
    assert r.json()["status"] == "tampered"


def test_deleted_stored_file_is_detected(world):
    doc = world.upload(world.make_case()["id"])
    world.app.state.storage.delete(_version(world, doc["id"]).storage_key)
    report = _assert_blocked_and_flagged(world, doc["id"])
    assert any("missing" in r for r in report["reasons"])


def test_database_hash_rewrite_is_caught_by_ledger(world):
    doc = world.upload(world.make_case()["id"])
    with world.app.state.session_factory() as db:
        v = db.execute(select(DocumentVersion).where(DocumentVersion.document_id == doc["id"])).scalar_one()
        v.sha256 = hashlib.sha256(b"forged").hexdigest()
        db.commit()
    report = _assert_blocked_and_flagged(world, doc["id"])
    assert any("ledger" in r for r in report["reasons"])


def test_ledger_record_edit_is_caught(world):
    doc = world.upload(world.make_case()["id"])
    block = world.client.get(f"/api/ledger/tx/{doc['versions'][0]['ledger_tx_id']}", headers=world.h("auditor1")).json()
    world.app.state.ledger._tamper(block["index"], payload=dict(block["payload"], sha256=hashlib.sha256(b"forged").hexdigest()))
    report = _assert_blocked_and_flagged(world, doc["id"])
    assert any("Ledger record failed" in r for r in report["reasons"])


def test_ciphertext_swapped_between_versions_is_detected(world):
    doc = world.upload(world.make_case()["id"])
    world.client.post(f"/api/documents/{doc['id']}/versions", headers=world.h("officer1"),
                      files={"file": ("v2.txt", b"second version", "text/plain")})
    s = world.app.state.storage
    k1, k2 = _version(world, doc["id"], 1).storage_key, _version(world, doc["id"], 2).storage_key
    s.put(k1, s.get(k2))  # attacker copies v2's blob over v1
    _assert_blocked_and_flagged(world, doc["id"])


# ---- failure modes -----------------------------------------------------------------------------
def _nothing_stored(world):
    with world.app.state.session_factory() as db:
        assert db.scalar(select(func.count(Document.id))) == 0
    mongo = world.app.state.mongo
    assert mongo.db["blobs.files"].count_documents({}) == 0 and mongo.doc_meta.count_documents({}) == 0


def test_ledger_outage_refuses_upload_and_leaves_nothing_behind(world, monkeypatch):
    case = world.make_case()

    def boom(*a, **k):
        raise RuntimeError("ledger down")

    monkeypatch.setattr(world.app.state.ledger, "anchor", boom)
    world.upload(case["id"], expect=503)
    _nothing_stored(world)


def test_failed_final_commit_undoes_the_external_writes(world):
    """PostgreSQL, MongoDB and the ledger can't share a transaction: if the last commit fails, the blob and the
    MongoDB record written earlier must be removed."""
    state = world.app.state
    doc = world.upload(world.make_case()["id"])
    row = _version(world, doc["id"])
    assert state.storage.exists(row.storage_key) and state.mongo.doc_meta.count_documents({}) == 1

    class FailingSession:
        def commit(self):
            raise RuntimeError("postgres went away")

        def rollback(self):
            pass

    with pytest.raises(HTTPException) as exc:
        commit_or_compensate(state, FailingSession(), row)
    assert exc.value.status_code == 503
    assert not state.storage.exists(row.storage_key) and state.mongo.doc_meta.count_documents({}) == 0


def test_ai_outage_never_blocks_filing(world):
    world.app.state.ai = HttpAI("http://ai.invalid", "k", transport=httpx.MockTransport(lambda req: httpx.Response(500)))
    doc = world.upload(world.make_case()["id"])
    v = doc["versions"][0]
    assert v["ledger_tx_id"] and v["ai_provider"].startswith("unavailable")
    assert doc["doc_type"] == "other"


def _fake_ai_transport(seen: dict):
    def handler(req: httpx.Request) -> httpx.Response:
        seen[req.url.path] = req.headers.get("x-internal-key")
        if req.url.path == "/ai/process":
            return httpx.Response(200, json={
                "ocr": {"text": "Handwritten note about Case Zebra", "language": "eng", "confidence": 0.8,
                        "method": "tesseract_image", "pages": [1], "needs_review": False},
                "classification": {"doc_type": "witness_statement", "confidence": 0.77, "scores": {"witness_statement": 0.77}},
                "entities": {"persons": ["Zed Person"]}, "tags": ["witness"],
                "embedding": [1.0, 0.0, 0.0], "engine": "sentinel-ai-test",
            })
        if req.url.path == "/ai/embed":
            return httpx.Response(200, json={"vectors": [[1.0, 0.0, 0.0]], "dim": 3})
        if req.url.path == "/ai/summarize":
            return httpx.Response(200, json={"summary": "A short note about Case Zebra."})
        if req.url.path == "/ai/summarize-case":
            import json as _j

            docs = _j.loads(req.content)["documents"]
            return httpx.Response(200, json={"overall": f"Case with {len(docs)} document(s).",
                                             "by_type": {d["doc_type"]: "summary" for d in docs}, "documents": len(docs)})
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def test_external_ai_service_plugs_in_behind_the_contract(world):
    seen: dict = {}
    world.app.state.ai = HttpAI("http://ai.local", "secret-key", transport=_fake_ai_transport(seen))
    doc = world.upload(world.make_case()["id"], data=b"\x89PNG\r\n\x1a\nxxxx", name="scan.png")
    v = doc["versions"][0]
    assert seen == {"/ai/process": "secret-key"}
    assert doc["doc_type"] == "witness_statement" and v["ai_provider"] == "sentinel-ai-test"
    assert v["ai_entities"]["persons"] == ["Zed Person"] and v["language"] == "eng" and v["ocr_method"] == "tesseract_image"
    # OCR'd text is searchable (whole word) even though it is only stored encrypted
    r = world.client.get("/api/search", headers=world.h("officer1"), params={"q": "Zebra"})
    assert [d["document_id"] for d in r.json()["documents"]] == [doc["id"]]


def test_on_demand_summary_is_stored_encrypted(world):
    world.app.state.ai = HttpAI("http://ai.local", "k", transport=_fake_ai_transport({}))
    doc = world.upload(world.make_case()["id"], data=b"\x89PNG\r\n\x1a\nxxxx", name="scan.png")
    h = world.h("officer1")
    r = world.client.post(f"/api/documents/{doc['id']}/versions/1/summary", headers=h)
    assert r.status_code == 200 and r.json() == {"summary": "A short note about Case Zebra.", "available": True}
    assert world.client.get(f"/api/documents/{doc['id']}", headers=h).json()["versions"][0]["summary"].startswith("A short note")
    raw = world.app.state.mongo.doc_meta.find_one({"_id": docstore.meta_key(doc["id"], 1)})
    assert "short note" not in json.dumps(raw, default=str)
    # other officers cannot request or read it
    assert world.client.post(f"/api/documents/{doc['id']}/versions/1/summary", headers=world.h("officer2")).status_code == 404


def test_case_summary_uses_only_extracted_text_of_that_case(world):
    world.app.state.ai = HttpAI("http://ai.local", "k", transport=_fake_ai_transport({}))
    c1, c2 = world.make_case("officer1"), world.make_case("officer2", title="Other")
    png = b"\x89PNG\r\n\x1a\n"
    world.upload(c1["id"], data=png + b"xxxx", name="a.png", title="A")
    world.upload(c1["id"], data=png + b"yyyy", name="b.png", title="B")
    world.upload(c2["id"], "officer2", data=png + b"zzzz", name="c.png", title="C")
    r = world.client.post(f"/api/cases/{c1['id']}/summary", headers=world.h("officer1"))
    assert r.status_code == 200 and r.json()["available"] and r.json()["documents"] == 2
    assert r.json()["overall"] == "Case with 2 document(s)."
    assert world.client.post(f"/api/cases/{c1['id']}/summary", headers=world.h("officer2")).status_code == 404   # not their case
    assert world.client.post(f"/api/cases/{c1['id']}/summary", headers=world.h("admin1")).status_code == 403      # no content rights
    assert any(e["action"] == "CASE_SUMMARISED" for e in world.audit_actions())


def test_case_summary_without_text_or_ai(world):
    c = world.make_case("officer1")
    world.upload(c["id"], data=b"%PDF-1.4\n%%EOF", name="blank.pdf")   # nothing extractable
    assert world.client.post(f"/api/cases/{c['id']}/summary", headers=world.h("officer1")).status_code == 422
    c2 = world.make_case("officer1", title="With text")
    world.upload(c2["id"])                                              # stub AI has text but cannot summarise
    r = world.client.post(f"/api/cases/{c2['id']}/summary", headers=world.h("officer1"))
    assert r.status_code == 200 and r.json()["available"] is False


def test_summary_needs_text_and_ai(world):
    doc = world.upload(world.make_case()["id"], data=b"%PDF-1.4\n%%EOF", name="blank.pdf")  # no extractable text
    r = world.client.post(f"/api/documents/{doc['id']}/versions/1/summary", headers=world.h("officer1"))
    assert r.status_code == 422


def test_classification_feedback_is_recorded_for_retraining(world):
    doc = world.upload(world.make_case()["id"])  # AI says "fir"
    h = world.h("officer1")
    r = world.client.post(f"/api/documents/{doc['id']}/classification-feedback", headers=h, json={"correct_type": "police_report"})
    assert r.status_code == 204
    assert world.client.get(f"/api/documents/{doc['id']}", headers=h).json()["doc_type"] == "police_report"
    fb = world.app.state.mongo.feedback.find_one({"document_id": doc["id"]})
    assert fb["ai_type"] == "fir" and fb["correct_type"] == "police_report"
    assert "text" not in fb and "ocr_text" not in fb  # labels only, never content
    assert world.client.post(f"/api/documents/{doc['id']}/classification-feedback", headers=h, json={"correct_type": "bogus"}).status_code == 422
    assert world.client.post(f"/api/documents/{doc['id']}/classification-feedback", headers=world.h("officer2"), json={"correct_type": "fir"}).status_code == 404


def test_ai_result_defaults_are_sane():
    r = AIResult()
    assert r.doc_type == "other" and r.tags == [] and r.embedding is None
    assert issubclass(AIServiceError, Exception)
