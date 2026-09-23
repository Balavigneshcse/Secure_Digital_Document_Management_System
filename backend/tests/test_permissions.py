"""Rank-based station-wide access (officer -> station_head -> superintendent) and forensic/judge case sharing."""
from __future__ import annotations

from app.models import Case
from conftest import FIR_TEXT


def _upload(world, case_id, username):
    return world.client.post(
        f"/api/cases/{case_id}/documents", headers=world.h(username),
        data={"title": "Evidence", "doc_type": "auto"}, files={"file": ("f.txt", FIR_TEXT, "text/plain")},
    )


# ---------------------------------------------------------------------------------- rank-based station access
def test_plain_officer_sees_only_assigned_cases(world):
    world.add_user("other1", "officer")
    mine = world.make_case("officer1")
    other = world.make_case("other1")
    ids = {c["id"] for c in world.client.get("/api/cases", headers=world.h("officer1")).json()}
    assert mine["id"] in ids and other["id"] not in ids
    assert world.client.get(f"/api/cases/{other['id']}", headers=world.h("officer1")).status_code == 404


def test_station_head_sees_every_case_at_their_own_station_only(world):
    world.add_user("sho1", "officer", station="CPS", rank="station_head")
    world.add_user("other_station_officer", "officer", station="NPS")
    at_cps = world.make_case("officer1")  # created by a plain officer, sho1 is NOT assigned
    at_nps = world.make_case("other_station_officer")

    r = world.client.get(f"/api/cases/{at_cps['id']}", headers=world.h("sho1"))
    assert r.status_code == 200 and r.json()["document_count"] == 0  # content access -> a real count, not None

    ids = {c["id"] for c in world.client.get("/api/cases", headers=world.h("sho1")).json()}
    assert at_cps["id"] in ids and at_nps["id"] not in ids
    assert world.client.get(f"/api/cases/{at_nps['id']}", headers=world.h("sho1")).status_code == 404

    up = _upload(world, at_cps["id"], "sho1")  # full content access includes write, same as an assigned officer
    assert up.status_code == 201, up.text


def test_superintendent_sees_every_case_at_every_overseen_station(world):
    world.add_user("sp1", "officer", station=None, rank="superintendent")
    world.add_user("nps_officer", "officer", station="NPS")
    world.add_user("third_station_officer", "officer", station="XPS")
    world.oversee("sp1", "CPS")
    world.oversee("sp1", "NPS")
    at_cps = world.make_case("officer1")
    at_nps = world.make_case("nps_officer")
    at_xps = world.make_case("third_station_officer")

    ids = {c["id"] for c in world.client.get("/api/cases", headers=world.h("sp1")).json()}
    assert {at_cps["id"], at_nps["id"]} <= ids
    assert at_xps["id"] not in ids
    assert world.client.get(f"/api/cases/{at_xps['id']}", headers=world.h("sp1")).status_code == 404
    assert world.client.get(f"/api/cases/{at_nps['id']}", headers=world.h("sp1")).status_code == 200


def test_officer_promoted_or_demoted_by_admin_via_patch(world):
    officer_id = world.client.get("/api/users", headers=world.h("admin1")).json()
    oid = next(u["id"] for u in officer_id if u["username"] == "officer1")
    other = world.make_case("officer2")  # officer1 not assigned, not yet station_head

    assert world.client.get(f"/api/cases/{other['id']}", headers=world.h("officer1")).status_code == 404
    r = world.client.patch(f"/api/users/{oid}", headers=world.h("admin1"), json={"is_active": True, "rank": "station_head"})
    assert r.status_code == 200 and r.json()["rank"] == "station_head"
    assert world.client.get(f"/api/cases/{other['id']}", headers=world.h("officer1")).status_code == 200

    r2 = world.client.patch(f"/api/users/{oid}", headers=world.h("admin1"), json={"is_active": True, "rank": "officer"})
    assert r2.status_code == 200 and r2.json()["rank"] == "officer"
    assert world.client.get(f"/api/cases/{other['id']}", headers=world.h("officer1")).status_code == 404

    bad = world.client.patch(f"/api/users/{oid}", headers=world.h("admin1"), json={"is_active": True, "rank": "superintendent"})
    assert bad.status_code == 422  # only the operator CLI can grant multi-station oversight


# ---------------------------------------------------------------------------------------- forensic / judge shares
def test_forensic_and_judge_see_nothing_until_shared_then_exactly_that_case(world):
    world.add_user("forensic1", "forensic")
    world.add_user("judge1", "judge")
    c1 = world.make_case("officer1")
    c2 = world.make_case("officer1", title="Second case", fir_number="FIR-9/2026")

    for who in ("forensic1", "judge1"):
        assert world.client.get("/api/cases", headers=world.h(who)).json() == []
        assert world.client.get(f"/api/cases/{c1['id']}", headers=world.h(who)).status_code == 404

    r = world.client.post(f"/api/cases/{c1['id']}/shares", headers=world.h("officer1"), json={"user_id": world._uid("forensic1")})
    assert r.status_code == 201
    body = r.json()
    assert body["shares"][0]["username"] == "forensic1" and body["shares"][0]["shared_by"] == "officer1"
    world.client.post(f"/api/cases/{c1['id']}/shares", headers=world.h("officer1"), json={"user_id": world._uid("judge1")})

    ids = {c["id"] for c in world.client.get("/api/cases", headers=world.h("forensic1")).json()}
    assert ids == {c1["id"]}  # not c2
    assert world.client.get(f"/api/cases/{c2['id']}", headers=world.h("forensic1")).status_code == 404

    d = world.upload(c1["id"], "officer1")
    v = d["versions"][0]["version_no"]

    # judge: full read on a shared case, same as before this file's forensic model changed
    assert world.client.get(f"/api/documents/{d['id']}", headers=world.h("judge1")).status_code == 200
    assert world.client.get(f"/api/documents/{d['id']}/versions/{v}/download", headers=world.h("judge1")).status_code == 200
    assert world.client.get(f"/api/documents/{d['id']}/versions/{v}/verify", headers=world.h("judge1")).status_code == 200

    # forensic: can now upload its own findings to a shared case ...
    up = _upload(world, c1["id"], "forensic1")
    assert up.status_code == 201, up.text
    lab_doc = up.json()

    # ... but cannot read the officer's existing document (investigation files stay invisible) ...
    assert world.client.get(f"/api/documents/{d['id']}", headers=world.h("forensic1")).status_code == 404
    assert world.client.get(f"/api/documents/{d['id']}/versions/{v}/download", headers=world.h("forensic1")).status_code == 404
    assert world.client.get(f"/api/documents/{d['id']}/versions/{v}/verify", headers=world.h("forensic1")).status_code == 404

    # ... while it CAN read its own upload, and the officer can see it too
    lv = lab_doc["versions"][0]["version_no"]
    assert world.client.get(f"/api/documents/{lab_doc['id']}", headers=world.h("forensic1")).status_code == 200
    assert world.client.get(f"/api/documents/{lab_doc['id']}/versions/{lv}/download", headers=world.h("forensic1")).status_code == 200
    assert world.client.get(f"/api/documents/{lab_doc['id']}", headers=world.h("officer1")).status_code == 200

    # still no versioning anyone else's doc, no case creation, no AI-trigger actions
    assert world.client.post(f"/api/documents/{d['id']}/versions", headers=world.h("forensic1"),
                             files={"file": ("g.txt", b"x", "text/plain")}).status_code == 403
    assert world.client.post("/api/cases", headers=world.h("forensic1"),
                             json={"title": "x", "parties": []}).status_code == 403
    assert world.client.post(f"/api/documents/{lab_doc['id']}/versions/{lv}/summary", headers=world.h("forensic1")).status_code == 403


def test_share_revoke_removes_access(world):
    world.add_user("forensic1", "forensic")
    c1 = world.make_case("officer1")
    world.client.post(f"/api/cases/{c1['id']}/shares", headers=world.h("officer1"), json={"user_id": world._uid("forensic1")})
    assert world.client.get(f"/api/cases/{c1['id']}", headers=world.h("forensic1")).status_code == 200

    r = world.client.delete(f"/api/cases/{c1['id']}/shares/{world._uid('forensic1')}", headers=world.h("officer1"))
    assert r.status_code == 200 and r.json()["shares"] == []
    assert world.client.get(f"/api/cases/{c1['id']}", headers=world.h("forensic1")).status_code == 404


def test_admin_can_share_without_content_access_but_target_must_be_forensic_or_judge(world):
    world.add_user("forensic1", "forensic")
    c1 = world.make_case("officer1")
    # admin has view (not content) access to this case, and can still grant a share
    r = world.client.post(f"/api/cases/{c1['id']}/shares", headers=world.h("admin1"), json={"user_id": world._uid("forensic1")})
    assert r.status_code == 201

    bad = world.client.post(f"/api/cases/{c1['id']}/shares", headers=world.h("admin1"), json={"user_id": world._uid("officer2")})
    assert bad.status_code == 400  # can't "share" with a plain officer account

    dup = world.client.post(f"/api/cases/{c1['id']}/shares", headers=world.h("officer1"), json={"user_id": world._uid("forensic1")})
    assert dup.status_code == 409


def test_reviewers_endpoint_lists_only_forensic_and_judge(world):
    world.add_user("forensic1", "forensic")
    world.add_user("judge1", "judge")
    for who in ("officer1", "admin1"):
        rows = world.client.get("/api/users/reviewers", headers=world.h(who)).json()
        assert {u["role"] for u in rows} == {"forensic", "judge"}
    assert world.client.get("/api/users/reviewers", headers=world.h("auditor1")).status_code == 403


# --------------------------------------------------------------------------------------- content_scope vs can_read_content
def test_content_scope_query_agrees_with_can_read_content_per_case(world):
    """The list-query shortcut and the single-case check must never disagree."""
    from app.permissions import can_read_content

    world.add_user("sho1", "officer", station="CPS", rank="station_head")
    world.add_user("forensic1", "forensic")
    at_cps = world.make_case("officer1")
    elsewhere = world.make_case("officer2")
    world.client.post(f"/api/cases/{at_cps['id']}/shares", headers=world.h("officer1"), json={"user_id": world._uid("forensic1")})

    with world.app.state.session_factory() as db:
        cases = db.query(Case).all()
        for username in ("officer1", "officer2", "sho1", "forensic1"):
            u = world.user_row(db, username)
            listed_ids = {c["id"] for c in world.client.get("/api/cases", headers=world.h(username)).json()}
            for case in cases:
                # a case the single-object check says is content-readable must appear in the list endpoint, and vice versa
                assert can_read_content(db, u, case) == (case.id in listed_ids)
