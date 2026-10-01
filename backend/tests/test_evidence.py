"""Audio/video evidence, the in-browser viewer, chain of custody, the Section 63 certificate and digital signatures."""
from __future__ import annotations

from sqlalchemy import select

from app.models import DocumentVersion, Signature, SigningKey
from conftest import FIR_TEXT, PASSWORD

MP4 = b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom" + b"\x00" * 64  # header of a real MP4; enough for the check


def _setup(world):
    world.station_district("CPS", "KRR")
    world.add_user("krr_judge", "judge", station=None, rank="district_court", district="KRR")
    world.add_user("krr_lab", "forensic", station=None, district="KRR")
    case = world.make_case("officer1")
    world.client.post(f"/api/cases/{case['id']}/shares", headers=world.h("officer1"), json={"user_id": world._uid("krr_lab")})
    return case, world.upload(case["id"], "officer1", title="FIR 142")


def _tamper(world, doc_id):
    with world.app.state.session_factory() as db:
        v = db.execute(select(DocumentVersion).where(DocumentVersion.document_id == doc_id)).scalars().first()
        s = world.app.state.storage
        blob = bytearray(s.get(v.storage_key))
        blob[-1] ^= 1
        s.put(v.storage_key, bytes(blob))


def test_cctv_video_is_stored_hashed_and_verified_but_not_sent_to_the_ai(world):
    case, _ = _setup(world)
    r = world.client.post(f"/api/cases/{case['id']}/documents", headers=world.h("officer1"),
                          data={"title": "CCTV clip, Kovai Road", "doc_type": "auto"}, files={"file": ("cctv.mp4", MP4, "video/mp4")})
    assert r.status_code == 201, r.text
    d = r.json()
    v = d["versions"][0]
    assert d["doc_type"] == "evidence_record" and v["content_type"] == "video/mp4" and v["ai_provider"] == "not analysed (audio/video)"
    assert world.client.get(f"/api/documents/{d['id']}/versions/1/verify", headers=world.h("officer1")).json()["status"] == "verified"
    bad = world.client.post(f"/api/cases/{case['id']}/documents", headers=world.h("officer1"),
                            data={"title": "fake"}, files={"file": ("fake.mp4", b"MZ this is an exe", "video/mp4")})
    assert bad.status_code == 415
    world.app.state.settings.max_media_upload_mb = 0  # the media limit applies to media, not to documents
    big = world.client.post(f"/api/cases/{case['id']}/documents", headers=world.h("officer1"),
                            data={"title": "too big"}, files={"file": ("big.mp4", MP4, "video/mp4")})
    assert big.status_code == 413 and "Audio/video" in big.json()["detail"]


def test_viewing_in_the_browser_is_verified_and_recorded(world):
    case, fir = _setup(world)
    r = world.client.get(f"/api/documents/{fir['id']}/versions/1/download", headers=world.h("krr_judge"), params={"inline": "true"})
    assert r.status_code == 200 and r.headers["content-disposition"].startswith("inline") and r.content == FIR_TEXT
    t = world.client.get(f"/api/documents/{fir['id']}/versions/1/text", headers=world.h("krr_judge")).json()
    assert t["available"] and "FIRST INFORMATION REPORT" in t["text"]
    assert world.audit_actions(action="DOCUMENT_OPENED")[0]["actor_username"] == "krr_judge"
    _tamper(world, fir["id"])
    assert world.client.get(f"/api/documents/{fir['id']}/versions/1/download", headers=world.h("krr_judge"), params={"inline": "true"}).status_code == 409
    assert world.client.get(f"/api/documents/{fir['id']}/versions/1/text", headers=world.h("krr_judge")).status_code == 409


def test_chain_of_custody_lists_every_access_including_refused_ones(world):
    case, fir = _setup(world)
    world.client.get(f"/api/documents/{fir['id']}/versions/1/download", headers=world.h("krr_judge"))
    world.client.get(f"/api/documents/{fir['id']}", headers=world.h("krr_lab"))  # refused: not the lab's document
    c = world.client.get(f"/api/documents/{fir['id']}/custody", headers=world.h("krr_judge"))
    assert c.status_code == 200
    seen = [(e["actor"], e["action"]) for e in c.json()]
    assert ("officer1", "DOCUMENT_UPLOADED") in seen and ("krr_judge", "DOCUMENT_DOWNLOADED") in seen
    assert ("krr_lab", "ACCESS_DENIED") in seen
    assert world.client.get(f"/api/documents/{fir['id']}/custody", headers=world.h("krr_lab")).status_code in (403, 404)


def test_section_63_certificate_carries_the_proof_and_is_refused_for_a_tampered_file(world):
    case, fir = _setup(world)
    r = world.client.get(f"/api/documents/{fir['id']}/versions/1/certificate", headers=world.h("krr_judge"))
    assert r.status_code == 200, r.text
    cert = r.json()
    assert cert["integrity"]["status"] == "verified" and cert["integrity"]["sha256"] == fir["versions"][0]["sha256"]
    assert cert["integrity"]["ledger_tx_id"] == fir["versions"][0]["ledger_tx_id"]
    assert cert["case"]["case_number"] == case["case_number"] and cert["custody"] and cert["certificate_no"].startswith("SDMS/")
    issued = world.audit_actions(action="CERTIFICATE_ISSUED")[0]
    assert issued["detail"]["certificate_sha256"] == cert["certificate_sha256"]
    _tamper(world, fir["id"])
    assert world.client.get(f"/api/documents/{fir['id']}/versions/1/certificate", headers=world.h("krr_judge")).status_code == 409


def test_signatures_need_the_password_and_detect_forgery(world):
    case, fir = _setup(world)
    url = f"/api/documents/{fir['id']}/versions/1"
    assert world.client.post(f"{url}/sign", headers=world.h("officer1"), json={"password": "wrong-password"}).status_code == 400
    r = world.client.post(f"{url}/sign", headers=world.h("officer1"), json={"password": PASSWORD})
    assert r.status_code == 201 and r.json()["valid"] is True, r.text
    assert world.client.post(f"{url}/sign", headers=world.h("officer1"), json={"password": PASSWORD}).status_code == 409
    assert world.client.post(f"{url}/sign", headers=world.h("krr_judge"), json={"password": PASSWORD}).status_code == 403  # not the judge's document
    listing = world.client.get(f"{url}/signatures", headers=world.h("krr_judge")).json()
    assert [s["signer"] for s in listing["signatures"]] == ["officer1"] and listing["signatures"][0]["valid"]
    assert any(e["action"] == "SIGN_FAILED" for e in world.audit_actions())

    # a new version: the old signature still belongs to v1, and only the current version can be signed
    world.client.post(f"/api/documents/{fir['id']}/versions", headers=world.h("officer1"), data={"change_note": "corrected"},
                      files={"file": ("v2.txt", FIR_TEXT + b"Corrected.\n", "text/plain")})
    assert world.client.post(f"{url}/sign", headers=world.h("officer1"), json={"password": PASSWORD}).status_code == 409

    # forging: rewrite what was signed, or swap in another key - both are caught
    with world.app.state.session_factory() as db:
        s = db.execute(select(Signature)).scalar_one()
        s.statement = s.statement.replace('"version_no":1', '"version_no":2')
        db.commit()
    assert world.client.get(f"{url}/signatures", headers=world.h("officer1")).json()["signatures"][0]["valid"] is False
    with world.app.state.session_factory() as db:
        k = db.get(SigningKey, world._uid("officer1"))
        s = db.execute(select(Signature)).scalar_one()
        s.statement = s.statement.replace('"version_no":2', '"version_no":1')
        k.public_key = s.public_key = "A" * 43 + "="  # an attacker's key, put in both places
        db.commit()
    sig = world.client.get(f"{url}/signatures", headers=world.h("officer1")).json()["signatures"][0]
    assert sig["valid"] is False and any("ledger" in p or "match" in p for p in sig["problems"])


def test_forensic_lab_signs_its_own_report(world):
    case, _ = _setup(world)
    rep = world.client.post(f"/api/cases/{case['id']}/documents", headers=world.h("krr_lab"), data={"title": "DNA report"},
                            files={"file": ("dna.txt", b"Forensic laboratory report. Sample A matches.\n", "text/plain")}).json()
    r = world.client.post(f"/api/documents/{rep['id']}/versions/1/sign", headers=world.h("krr_lab"), json={"password": PASSWORD})
    assert r.status_code == 201 and r.json()["signer_role"] == "forensic"
    assert world.client.post(f"/api/documents/{rep['id']}/versions/1/sign", headers=world.h("officer1"), json={"password": PASSWORD}).status_code == 403
