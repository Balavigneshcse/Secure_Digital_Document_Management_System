"""Case stages, closing/reopening, time-limited sharing, station-head approval, and the prosecutor/defence roles."""
from __future__ import annotations

from sqlalchemy import select

from app.models import CaseShare
from app.permissions import can_read_document
from conftest import FIR_TEXT

CHARGE_SHEET = b"CHARGE SHEET\nFinal report under section 193 BNSS. The accused is charged with theft.\n"
STATEMENT = b"WITNESS STATEMENT\nStatement of Mr. Anand Rao recorded under section 180 BNSS.\n"
DIARY = b"CASE DIARY\nInvestigation notes: spot inspection done, suspects listed.\n"


def _court(world):
    world.station_district("CPS", "KRR")
    world.add_user("krr_judge", "judge", station=None, rank="district_court", district="KRR")


def _share(world, case_id, username, days=None, by="officer1"):
    body = {"user_id": world._uid(username), **({"days": days} if days else {})}
    return world.client.post(f"/api/cases/{case_id}/shares", headers=world.h(by), json=body)


def _verdict(world, case_id, user="krr_judge"):
    return world.client.post(f"/api/cases/{case_id}/verdict", headers=world.h(user),
                             json={"outcome": "convicted", "reasoning": "Proved beyond reasonable doubt on the evidence on record."})


def _docs(world, case_id, user):
    r = world.client.get(f"/api/cases/{case_id}/documents", headers=world.h(user))
    assert r.status_code == 200, r.text
    return {d["title"] for d in r.json()}


# ---------------------------------------------------------------------------------------------- stages / closing
def test_stage_moves_forward_only_with_a_charge_sheet_and_is_recorded(world):
    case = world.make_case("officer1")
    assert case["stage"] == "under_investigation"
    edit = {"stage": "charge_sheeted", "reason": "charge sheet filed"}
    assert world.client.patch(f"/api/cases/{case['id']}", headers=world.h("officer1"), json=edit).status_code == 409
    world.upload(case["id"], "officer1", data=CHARGE_SHEET, name="cs.txt", title="Charge sheet", doc_type="charge_sheet")
    r = world.client.patch(f"/api/cases/{case['id']}", headers=world.h("officer1"), json=edit)
    assert r.status_code == 200 and r.json()["stage"] == "charge_sheeted"
    h = world.client.get(f"/api/cases/{case['id']}/history", headers=world.h("officer1")).json()
    assert h[0]["changes"] == [{"field": "Stage", "old": "under_investigation", "new": "charge_sheeted"}]


def test_closed_case_refuses_uploads_until_the_judge_reopens_it(world):
    _court(world)
    case = world.make_case("officer1")
    world.upload(case["id"], "officer1")
    assert _verdict(world, case["id"]).status_code == 201
    c = world.client.get(f"/api/cases/{case['id']}", headers=world.h("officer1")).json()
    assert c["status"] == "closed" and c["stage"] == "judgment_delivered" and c["can_reopen"] is False
    world.upload(case["id"], "officer1", expect=409)

    reopen = {"reason": "High court remanded the case for fresh evidence"}
    assert world.client.post(f"/api/cases/{case['id']}/reopen", headers=world.h("officer1"), json=reopen).status_code == 403
    assert world.client.get(f"/api/cases/{case['id']}", headers=world.h("krr_judge")).json()["can_reopen"] is True
    r = world.client.post(f"/api/cases/{case['id']}/reopen", headers=world.h("krr_judge"), json=reopen)
    assert r.status_code == 200 and r.json()["status"] == "open" and r.json()["stage"] == "in_trial"
    e = world.client.get(f"/api/cases/{case['id']}/history", headers=world.h("officer1")).json()[0]
    assert e["editor"] == "krr_judge" and e["reason"] == reopen["reason"] and {"field": "Status", "old": "closed", "new": "open"} in e["changes"]
    assert world.client.post(f"/api/cases/{case['id']}/reopen", headers=world.h("krr_judge"), json=reopen).status_code == 409

    world.upload(case["id"], "officer1", title="Fresh evidence")  # open again: filing works
    assert _verdict(world, case["id"]).status_code == 201          # and the court can decide again
    docs = world.client.get(f"/api/cases/{case['id']}/documents", headers=world.h("krr_judge")).json()
    assert sum(d["doc_type"] == "judgment" for d in docs) == 2       # the first judgment stays on file


# ---------------------------------------------------------------------------------------------- share expiry
def test_a_time_limited_share_stops_working_when_it_expires_and_can_be_renewed(world):
    world.add_user("lab", "forensic", station=None)
    case = world.make_case("officer1")
    r = _share(world, case["id"], "lab", days=7)
    assert r.status_code == 201
    share = r.json()["shares"][0]
    assert share["expires_at"] and share["expired"] is False
    world.upload(case["id"], "lab", title="Lab report")
    assert world.client.get(f"/api/cases/{case['id']}", headers=world.h("lab")).status_code == 200

    with world.app.state.session_factory() as db:  # let the week pass
        db.execute(select(CaseShare)).scalar_one().expires_at = "2000-01-01T00:00:00.000000Z"
        db.commit()
    assert world.client.get(f"/api/cases/{case['id']}", headers=world.h("lab")).status_code == 404
    assert case["id"] not in {c["id"] for c in world.client.get("/api/cases", headers=world.h("lab")).json()}
    assert world.client.get(f"/api/cases/{case['id']}", headers=world.h("officer1")).json()["shares"][0]["expired"] is True

    assert _share(world, case["id"], "lab", days=30).status_code == 201  # renewing an expired share
    assert world.client.get(f"/api/cases/{case['id']}", headers=world.h("lab")).status_code == 200
    assert _share(world, case["id"], "lab").status_code == 409            # but not a live one twice


# ---------------------------------------------------------------------------------------------- approval
def test_fir_waits_for_the_station_head_before_the_court_sees_it(world):
    _court(world)
    world.add_user("sho1", "officer", station="CPS", rank="station_head")
    case = world.make_case("officer1")
    fir = world.upload(case["id"], "officer1", title="FIR 142", doc_type="fir")
    assert fir["approval_status"] == "pending"
    other = world.upload(case["id"], "officer1", data=STATEMENT, name="st.txt", title="Statement", doc_type="witness_statement")
    assert other["approval_status"] == "not_required"

    # the court side doesn't see a pending FIR - not in the list, not by id, not in search
    assert _docs(world, case["id"], "krr_judge") == {"Statement"}
    assert world.client.get(f"/api/documents/{fir['id']}", headers=world.h("krr_judge")).status_code == 404
    hits = world.client.get("/api/search", headers=world.h("krr_judge"), params={"q": "FIR"}).json()["documents"]
    assert fir["id"] not in {d["document_id"] for d in hits}
    assert world.client.get(f"/api/cases/{case['id']}", headers=world.h("krr_judge")).json()["document_count"] == 1

    # only the station head decides; returning needs a note; the filer corrects it and it goes back for approval
    dec = lambda user, **b: world.client.post(f"/api/documents/{fir['id']}/approval", headers=world.h(user), json=b)  # noqa: E731
    assert dec("officer1", decision="approve").status_code == 403
    assert [a["document_id"] for a in world.client.get("/api/approvals", headers=world.h("sho1")).json()] == [fir["id"]]
    assert dec("sho1", decision="return").status_code == 422
    r = dec("sho1", decision="return", note="Add the time of occurrence")
    assert r.status_code == 200 and r.json()["approval_status"] == "returned"
    dash = world.client.get("/api/dashboard", headers=world.h("officer1")).json()
    assert dash["returned"][0]["note"] == "Add the time of occurrence"
    r = world.client.post(f"/api/documents/{fir['id']}/versions", headers=world.h("officer1"), data={"change_note": "time of occurrence added"},
                          files={"file": ("fir2.txt", FIR_TEXT + b"Time: 21:30 hours\n", "text/plain")})
    assert r.json()["approval_status"] == "pending"
    r = dec("sho1", decision="approve")
    assert r.status_code == 200 and r.json()["approval_status"] == "approved" and r.json()["approved_version"] == 2
    assert dec("sho1", decision="approve").status_code == 409

    assert _docs(world, case["id"], "krr_judge") == {"Statement", "FIR 142"}
    kinds = [e["kind"] for e in world.client.get(f"/api/documents/{fir['id']}/history", headers=world.h("krr_judge")).json()]
    assert kinds == ["approval", "version", "approval"]


def test_no_approval_step_where_the_station_has_no_station_head(world):
    case = world.make_case("officer1")
    assert world.upload(case["id"], "officer1", doc_type="fir")["approval_status"] == "not_required"


# ---------------------------------------------------------------------------------------------- prosecutor / defence
def test_prosecutor_reads_the_case_files_its_own_and_cannot_alter_police_documents(world):
    world.add_user("pp", "prosecutor", station=None)
    case = world.make_case("officer1")
    fir = world.upload(case["id"], "officer1", title="FIR")
    assert world.client.get(f"/api/documents/{fir['id']}", headers=world.h("pp")).status_code == 404  # not shared yet
    assert _share(world, case["id"], "pp").status_code == 201
    assert world.client.get(f"/api/documents/{fir['id']}/versions/1/download", headers=world.h("pp")).status_code == 200
    filing = world.upload(case["id"], "pp", data=b"Petition before the court: bail opposed.\n", name="p.txt", title="Objection to bail")
    assert world.client.patch(f"/api/documents/{filing['id']}", headers=world.h("pp"), json={"title": "Objection to bail (final)", "reason": "wording"}).status_code == 200
    assert world.client.patch(f"/api/documents/{fir['id']}", headers=world.h("pp"), json={"title": "x", "reason": "trying"}).status_code == 403
    assert world.client.patch(f"/api/documents/{filing['id']}", headers=world.h("officer1"), json={"title": "x", "reason": "trying"}).status_code == 403


def test_defence_sees_only_what_the_defence_is_entitled_to(world):
    world.add_user("adv", "defence", station=None)
    case = world.make_case("officer1")
    for title, data, t in (("FIR", FIR_TEXT, "fir"), ("Statement", STATEMENT, "witness_statement"),
                           ("Case diary", DIARY, "investigation_record"), ("Charge sheet", CHARGE_SHEET, "charge_sheet")):
        world.upload(case["id"], "officer1", data=data, name=f"{t}.txt", title=title, doc_type=t)
    assert _share(world, case["id"], "adv").status_code == 201
    mine = world.upload(case["id"], "adv", data=b"Bail application on behalf of the accused.\n", name="bail.txt", title="Bail application")

    assert _docs(world, case["id"], "adv") == {"FIR", "Bail application"}  # during investigation: the FIR only
    world.client.patch(f"/api/cases/{case['id']}", headers=world.h("officer1"), json={"stage": "charge_sheeted", "reason": "charge sheet filed"})
    assert _docs(world, case["id"], "adv") == {"FIR", "Statement", "Charge sheet", "Bail application"}  # never the case diary
    hits = {d["title"] for d in world.client.get("/api/search", headers=world.h("adv"), params={"q": "case"}).json()["documents"]}
    assert "Case diary" not in hits

    # the SQL scope used by search agrees with the per-document rule, document by document
    with world.app.state.session_factory() as db:
        from app.models import Case, Document, User
        from app.permissions import content_scope, document_scope
        u = db.execute(select(User).where(User.username == "adv")).scalar_one()
        c = db.get(Case, case["id"])
        allowed = set(db.execute(select(Document.id).join(Case, Case.id == Document.case_id)
                                 .where(content_scope(u), document_scope(u))).scalars())
        assert allowed == {d.id for d in db.execute(select(Document)).scalars() if can_read_document(db, u, c, d)}
        assert mine["id"] in allowed
