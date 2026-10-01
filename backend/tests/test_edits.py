"""Editing case details and documents: who may, what is recorded, and that the record can't be quietly changed."""
from __future__ import annotations

from sqlalchemy import select

from app.models import EditRecord
from conftest import FIR_TEXT

LAB_V1 = b"Forensic laboratory report\nSample A matches.\n"
LAB_V2 = b"Forensic laboratory report\nSample A does not match.\n"


def _setup(world):
    world.station_district("CPS", "KRR")
    world.add_user("krr_judge", "judge", station=None, rank="district_court", district="KRR")
    world.add_user("krr_lab", "forensic", station=None, district="KRR")
    case = world.make_case("officer1")
    r = world.client.post(f"/api/cases/{case['id']}/shares", headers=world.h("officer1"), json={"user_id": world._uid("krr_lab")})
    assert r.status_code == 201, r.text
    return case


def _edit_case(world, case_id, user="officer1", **body):
    body.setdefault("reason", "corrected after re-checking the complaint")
    return world.client.patch(f"/api/cases/{case_id}", headers=world.h(user), json=body)


def _history(world, case_id, user):
    r = world.client.get(f"/api/cases/{case_id}/history", headers=world.h(user))
    assert r.status_code == 200, r.text
    return r.json()


def _lab_upload(world, case_id, title="DNA report"):
    r = world.client.post(f"/api/cases/{case_id}/documents", headers=world.h("krr_lab"),
                          data={"title": title, "doc_type": "auto"}, files={"file": ("lab.txt", LAB_V1, "text/plain")})
    assert r.status_code == 201, r.text
    return r.json()


def test_case_edit_is_recorded_with_old_and_new_values_and_the_judge_can_see_it(world):
    case = _setup(world)
    r = _edit_case(world, case["id"], title="Theft at the vegetable market", fir_number="FIR-143/2026",
                   parties=[{"name": "Ramesh Kumar", "role": "complainant"}, {"name": "Suresh P", "role": "accused"}])
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["title"] == "Theft at the vegetable market" and out["fir_number"] == "FIR-143/2026" and len(out["parties"]) == 2

    h = _history(world, case["id"], "krr_judge")  # the judge never edited anything, and sees exactly what changed
    assert len(h) == 1
    e = h[0]
    assert e["kind"] == "case" and e["editor"] == "officer1" and e["editor_role"] == "officer" and e["verified"] is True
    assert e["reason"] == "corrected after re-checking the complaint" and e["ts"].endswith("Z")
    changes = {c["field"]: (c["old"], c["new"]) for c in e["changes"]}
    assert changes["Title"] == ("Theft at market", "Theft at the vegetable market")
    assert changes["FIR number"] == ("FIR-142/2026", "FIR-143/2026")
    assert changes["Parties"] == ("Ramesh Kumar (complainant)", "Ramesh Kumar (complainant); Suresh P (accused)")
    assert "Case type" not in changes  # untouched fields are not listed

    # the audit log (read by auditors, who may not see case data) names the fields and a hash - never the values
    a = world.audit_actions(action="CASE_EDITED")[0]
    assert sorted(a["detail"]["fields"]) == ["FIR number", "Parties", "Title"] and len(a["detail"]["record_hash"]) == 64
    assert "vegetable" not in str(a["detail"])


def test_case_edit_rules(world):
    case = _setup(world)
    assert _edit_case(world, case["id"], title="Theft at market").status_code == 400          # nothing changed
    assert world.client.patch(f"/api/cases/{case['id']}", headers=world.h("officer1"), json={"title": "x"}).status_code == 422  # no reason
    assert _edit_case(world, case["id"], title="   ").status_code == 422
    assert _edit_case(world, case["id"], "officer2", title="x").status_code == 404           # not assigned: the case doesn't exist for them
    assert _edit_case(world, case["id"], "krr_judge", title="x").status_code == 403
    assert _edit_case(world, case["id"], "krr_lab", title="x").status_code == 403
    assert _edit_case(world, case["id"], "admin1", case_type="burglary").status_code == 200  # station admin manages case metadata
    assert _history(world, case["id"], "officer1")[0]["editor"] == "admin1"
    assert world.client.get(f"/api/cases/{case['id']}", headers=world.h("officer1")).json()["can_edit"] is True
    assert world.client.get(f"/api/cases/{case['id']}", headers=world.h("krr_judge")).json()["can_edit"] is False


def test_closed_case_is_frozen(world):
    case = _setup(world)
    doc = world.upload(case["id"], "officer1")
    r = world.client.post(f"/api/cases/{case['id']}/verdict", headers=world.h("krr_judge"),
                          json={"outcome": "acquitted", "reasoning": "The prosecution did not prove the charge beyond reasonable doubt."})
    assert r.status_code == 201, r.text
    assert _edit_case(world, case["id"], title="changed after the verdict").status_code == 409
    assert world.client.get(f"/api/cases/{case['id']}", headers=world.h("officer1")).json()["can_edit"] is False
    r = world.client.patch(f"/api/documents/{doc['id']}", headers=world.h("officer1"), json={"title": "x", "reason": "late change"})
    assert r.status_code == 409
    r = world.client.post(f"/api/documents/{doc['id']}/versions", headers=world.h("officer1"), data={"change_note": "late change"},
                          files={"file": ("v2.txt", b"rewritten", "text/plain")})
    assert r.status_code == 409


def test_document_details_edit_and_new_version_are_recorded(world):
    case = _setup(world)
    doc = world.upload(case["id"], "officer1")
    r = world.client.patch(f"/api/documents/{doc['id']}", headers=world.h("officer1"),
                           json={"title": "FIR 142 (corrected)", "description": "Date of offence corrected", "reason": "typing error in the title"})
    assert r.status_code == 200 and r.json()["title"] == "FIR 142 (corrected)"
    v2 = FIR_TEXT + b"\nSupplementary: one gold ring recovered on 14/03/2026.\n"
    r = world.client.post(f"/api/documents/{doc['id']}/versions", headers=world.h("officer1"),
                          data={"change_note": "added the recovery of the ring"}, files={"file": ("fir_v2.txt", v2, "text/plain")})
    assert r.status_code == 201, r.text
    assert world.client.post(f"/api/documents/{doc['id']}/versions", headers=world.h("officer1"),
                             files={"file": ("v3.txt", b"x", "text/plain")}).status_code == 422  # a change note is mandatory

    h = world.client.get(f"/api/documents/{doc['id']}/history", headers=world.h("krr_judge")).json()
    assert [e["kind"] for e in h] == ["version", "document"] and all(e["verified"] for e in h)
    assert h[0]["version_no"] == 2 and h[0]["reason"] == "added the recovery of the ring"
    assert doc["versions"][0]["sha256"] in h[0]["changes"][0]["old"] and "v2 - fir_v2.txt" in h[0]["changes"][0]["new"]
    assert {c["field"]: c["new"] for c in h[1]["changes"]} == {"Title": "FIR 142 (corrected)", "Description": "Date of offence corrected"}
    assert {e["kind"] for e in _history(world, case["id"], "krr_judge")} == {"version", "document"}  # also on the case page

    # what the new version changed, line by line
    d = world.client.get(f"/api/documents/{doc['id']}/versions/2/diff", headers=world.h("krr_judge")).json()
    assert d["available"] and d["from_version"] == 1 and d["added"] >= 1 and d["removed"] == 0
    assert any(ln["op"] == "+" and "gold ring" in ln["text"] for ln in d["lines"])
    assert world.client.get(f"/api/documents/{doc['id']}/versions/1/diff", headers=world.h("officer1")).json()["available"] is False


def test_a_document_is_edited_only_by_the_department_that_filed_it(world):
    case = _setup(world)
    officer_doc = world.upload(case["id"], "officer1")
    lab_doc = _lab_upload(world, case["id"])
    edit = {"title": "changed", "reason": "testing who may edit"}

    def new_version(doc_id, user):
        return world.client.post(f"/api/documents/{doc_id}/versions", headers=world.h(user),
                                 data={"change_note": "testing who may edit"}, files={"file": ("x.txt", LAB_V2, "text/plain")})

    # the lab edits and re-files its own report ...
    r = world.client.patch(f"/api/documents/{lab_doc['id']}", headers=world.h("krr_lab"), json={"title": "DNA report (final)", "reason": "final wording"})
    assert r.status_code == 200, r.text
    assert new_version(lab_doc["id"], "krr_lab").status_code == 201
    # ... the police can read it but never alter the lab's findings
    assert world.client.patch(f"/api/documents/{lab_doc['id']}", headers=world.h("officer1"), json=edit).status_code == 403
    assert new_version(lab_doc["id"], "officer1").status_code == 403
    # the lab cannot touch (or even see) the officer's document; the judge edits nothing
    assert world.client.patch(f"/api/documents/{officer_doc['id']}", headers=world.h("krr_lab"), json=edit).status_code == 404
    assert world.client.get(f"/api/documents/{officer_doc['id']}/history", headers=world.h("krr_lab")).status_code == 404
    assert world.client.get(f"/api/documents/{officer_doc['id']}/versions/1/diff", headers=world.h("krr_lab")).status_code == 404
    assert world.client.patch(f"/api/documents/{officer_doc['id']}", headers=world.h("krr_judge"), json=edit).status_code == 403

    # history is scoped like the documents: the lab sees its own edits, the officer and judge see all, the admin none
    assert world.client.patch(f"/api/documents/{officer_doc['id']}", headers=world.h("officer1"), json=edit).status_code == 200
    assert {e["document_id"] for e in _history(world, case["id"], "krr_lab")} == {lab_doc["id"]}
    assert {e["document_id"] for e in _history(world, case["id"], "officer1")} == {lab_doc["id"], officer_doc["id"]}
    assert _history(world, case["id"], "admin1") == []
    diff = world.client.get(f"/api/documents/{lab_doc['id']}/versions/2/diff", headers=world.h("officer1")).json()
    assert any(ln["op"] == "-" and "matches" in ln["text"] for ln in diff["lines"])


def test_altering_or_deleting_an_edit_record_is_detected(world):
    case = _setup(world)
    assert _edit_case(world, case["id"], title="First correction").status_code == 200
    assert _edit_case(world, case["id"], title="Second correction").status_code == 200
    with world.app.state.session_factory() as db:
        first, second = db.execute(select(EditRecord).order_by(EditRecord.id)).scalars().all()
        first.changes = first.changes.replace("Theft at market", "Something else")  # rewrite what the old value was
        db.delete(second)                                                           # and hide the other edit entirely
        db.commit()
    newest, oldest = _history(world, case["id"], "krr_judge")
    assert newest["verified"] is False and "missing" in newest["problem"] and newest["editor"] == "officer1"
    assert [c["field"] for c in newest["changes"]] == ["Title"]  # the audit chain still says which field was edited, and when
    assert oldest["verified"] is False and "altered" in oldest["problem"]


def test_correcting_the_document_type_is_an_edit_too(world):
    case = _setup(world)
    doc = world.upload(case["id"], "officer1")
    lab_doc = _lab_upload(world, case["id"])
    fb = {"correct_type": "police_report"}
    assert world.client.post(f"/api/documents/{doc['id']}/classification-feedback", headers=world.h("officer1"), json=fb).status_code == 204
    e = world.client.get(f"/api/documents/{doc['id']}/history", headers=world.h("krr_judge")).json()[0]
    assert e["kind"] == "document" and e["verified"] and e["changes"] == [{"field": "Document type", "old": "fir", "new": "police_report"}]
    # relabelling the lab's report would be the police changing the lab's document
    assert world.client.post(f"/api/documents/{lab_doc['id']}/classification-feedback", headers=world.h("officer1"), json=fb).status_code == 403
