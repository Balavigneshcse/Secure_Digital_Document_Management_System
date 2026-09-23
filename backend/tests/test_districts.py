"""Districts, district/high court judges, and the forensic lab's upload-only / own-documents-only access."""
from __future__ import annotations

from conftest import FIR_TEXT


def _upload(world, case_id, username, title="Evidence"):
    return world.client.post(
        f"/api/cases/{case_id}/documents", headers=world.h(username),
        data={"title": title, "doc_type": "auto"}, files={"file": ("f.txt", FIR_TEXT, "text/plain")},
    )


def test_district_court_judge_sees_every_case_in_their_district_only(world):
    world.station_district("CPS", "KRR")
    world.add_user("other_district_officer", "officer", station="XPS")
    world.station_district("XPS", "CHN")
    world.add_user("krr_judge", "judge", station=None, rank="district_court", district="KRR")

    in_district = world.make_case("officer1")
    out_of_district = world.make_case("other_district_officer")

    ids = {c["id"] for c in world.client.get("/api/cases", headers=world.h("krr_judge")).json()}
    assert in_district["id"] in ids and out_of_district["id"] not in ids
    r = world.client.get(f"/api/cases/{out_of_district['id']}", headers=world.h("krr_judge"))
    assert r.status_code == 404

    # full read access (unlike forensic), no share needed
    d = world.upload(in_district["id"], "officer1")
    v = d["versions"][0]["version_no"]
    assert world.client.get(f"/api/documents/{d['id']}", headers=world.h("krr_judge")).status_code == 200
    assert world.client.get(f"/api/documents/{d['id']}/versions/{v}/download", headers=world.h("krr_judge")).status_code == 200


def test_high_court_judge_sees_every_district(world):
    world.station_district("CPS", "KRR")
    world.add_user("chn_officer", "officer", station="XPS")
    world.station_district("XPS", "CHN")
    world.add_user("hc_judge", "judge", station=None, rank="high_court")

    c1 = world.make_case("officer1")
    c2 = world.make_case("chn_officer")
    ids = {c["id"] for c in world.client.get("/api/cases", headers=world.h("hc_judge")).json()}
    assert {c1["id"], c2["id"]} <= ids


def test_forensic_lab_can_upload_but_only_reads_its_own_documents(world):
    world.station_district("CPS", "KRR")
    world.add_user("krr_lab", "forensic", station=None, district="KRR")
    case = world.make_case("officer1")
    r = world.client.post(f"/api/cases/{case['id']}/shares", headers=world.h("officer1"), json={"user_id": world._uid("krr_lab")})
    assert r.status_code == 201, r.text

    officer_doc = world.upload(case["id"], "officer1", title="FIR")
    r = _upload(world, case["id"], "krr_lab", title="DNA report")
    assert r.status_code == 201, r.text
    lab_doc = r.json()

    # the lab sees only its own document in the list - the officer's FIR is invisible, not even its title
    listed = {d["id"]: d["title"] for d in world.client.get(f"/api/cases/{case['id']}/documents", headers=world.h("krr_lab")).json()}
    assert listed == {lab_doc["id"]: "DNA report"}

    # can open/download its own upload
    v = lab_doc["versions"][0]["version_no"]
    assert world.client.get(f"/api/documents/{lab_doc['id']}", headers=world.h("krr_lab")).status_code == 200
    assert world.client.get(f"/api/documents/{lab_doc['id']}/versions/{v}/download", headers=world.h("krr_lab")).status_code == 200

    # cannot open the officer's document even by guessing its id directly
    ov = officer_doc["versions"][0]["version_no"]
    assert world.client.get(f"/api/documents/{officer_doc['id']}", headers=world.h("krr_lab")).status_code == 404
    assert world.client.get(f"/api/documents/{officer_doc['id']}/versions/{ov}/download", headers=world.h("krr_lab")).status_code == 404

    # the officer (and any judge later shared/authorised) sees BOTH documents, including the lab's evidence
    both = {d["id"] for d in world.client.get(f"/api/cases/{case['id']}/documents", headers=world.h("officer1")).json()}
    assert both == {officer_doc["id"], lab_doc["id"]}


def test_forensic_cannot_add_a_version_to_someone_elses_document(world):
    world.station_district("CPS", "KRR")
    world.add_user("krr_lab", "forensic", station=None, district="KRR")
    case = world.make_case("officer1")
    world.client.post(f"/api/cases/{case['id']}/shares", headers=world.h("officer1"), json={"user_id": world._uid("krr_lab")})
    officer_doc = world.upload(case["id"], "officer1")
    r = world.client.post(f"/api/documents/{officer_doc['id']}/versions", headers=world.h("krr_lab"),
                          files={"file": ("x.txt", b"x", "text/plain")})
    assert r.status_code == 403  # upload_version stays officer-only, even for the lab's own case access


def test_sharing_a_case_with_an_out_of_district_forensic_lab_is_rejected(world):
    world.station_district("CPS", "KRR")
    world.add_user("chn_lab", "forensic", station=None, district="CHN")
    case = world.make_case("officer1")  # at CPS / KRR
    r = world.client.post(f"/api/cases/{case['id']}/shares", headers=world.h("officer1"), json={"user_id": world._uid("chn_lab")})
    assert r.status_code == 400
    assert "district" in r.json()["detail"].lower()


def test_reviewers_picker_hides_other_districts_forensic_labs(world):
    world.station_district("CPS", "KRR")
    world.add_user("krr_lab", "forensic", station=None, district="KRR")
    world.add_user("chn_lab", "forensic", station=None, district="CHN")
    world.add_user("some_judge", "judge", station=None)
    names = {u["username"] for u in world.client.get("/api/users/reviewers", headers=world.h("officer1")).json()}
    assert "krr_lab" in names and "chn_lab" not in names and "some_judge" in names  # judges are never filtered
