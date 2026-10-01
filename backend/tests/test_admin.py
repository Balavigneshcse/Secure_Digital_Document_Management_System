"""Forgotten passwords, the system administrator, and the dashboard / alerts."""
from __future__ import annotations

from sqlalchemy import select

from app.models import DocumentVersion


def _uid(world, username, as_user="admin1"):
    return next(u["id"] for u in world.client.get("/api/users", headers=world.h(as_user)).json() if u["username"] == username)


def test_admin_resets_a_forgotten_password(world):
    world.login("officer1")
    old_headers = world.h("officer1")
    r = world.client.post(f"/api/users/{_uid(world, 'officer1')}/reset-password", headers=world.h("admin1"))
    assert r.status_code == 200
    temp = r.json()["temporary_password"]
    assert len(temp) >= 12 and temp not in str(world.audit_actions(action="PASSWORD_RESET"))  # never logged in clear
    assert world.client.get("/api/cases", headers=old_headers).status_code == 401  # signed out everywhere

    # the temporary password works, but only together with the authenticator, and must be changed first
    r = world.client.post("/api/auth/login", json={"username": "officer1", "password": temp})
    assert r.status_code == 200 and r.json()["stage"] == "mfa_required"
    t = r.json()["token"]
    r = world.client.post("/api/auth/mfa/verify", headers={"Authorization": f"Bearer {t}"}, json={"code": world.code("officer1")})
    assert r.json()["must_change_password"] is True
    h = {"Authorization": f"Bearer {r.json()['token']}"}
    assert world.client.get("/api/cases", headers=h).status_code == 403
    assert world.client.post("/api/auth/change-password", headers=h,
                             json={"current_password": temp, "new_password": "Brand-New-Pass9"}).status_code == 200

    # a station admin cannot reset an account outside their station's officers
    world.add_user("sys1", "admin", station=None, rank="system")
    aid = _uid(world, "auditor1", as_user="sys1")
    assert world.client.post(f"/api/users/{aid}/reset-password", headers=world.h("admin1")).status_code == 404
    assert world.client.post(f"/api/users/{aid}/reset-password", headers=world.h("sys1")).status_code == 200


def test_system_administrator_manages_every_kind_of_account(world):
    world.add_user("sys1", "admin", station=None, rank="system")
    world.station_district("CPS", "KRR")
    hs = world.h("sys1")
    org = world.client.get("/api/users/org", headers=hs).json()
    krr = next(d["id"] for d in org["districts"] if d["code"] == "KRR")
    cps = next(s["id"] for s in org["stations"] if s["code"] == "CPS")
    new = lambda **b: world.client.post("/api/users", headers=hs, json={"full_name": "X", "password": "Temp0rary-Pass", **b})  # noqa: E731

    assert new(username="krr.judge", role="judge", rank="district_court", district_id=krr).status_code == 201
    assert new(username="nodistrict.judge", role="judge", rank="district_court").status_code == 422
    assert new(username="krr.lab", role="forensic", district_id=krr).status_code == 201
    assert new(username="pp1", role="prosecutor").status_code == 201
    assert new(username="adv1", role="defence").status_code == 201
    assert new(username="cps.sho", role="officer", rank="station_head", station_id=cps).status_code == 201
    assert new(username="bad.rank", role="forensic", rank="high_court", district_id=krr).status_code == 422
    assert new(username="nostation", role="officer").status_code == 422

    everyone = {u["username"] for u in world.client.get("/api/users", headers=hs).json()}
    assert {"krr.judge", "krr.lab", "pp1", "adv1", "cps.sho", "auditor1", "officer1"} <= everyone
    station_view = {u["username"] for u in world.client.get("/api/users", headers=world.h("admin1")).json()}
    assert "krr.judge" not in station_view and "auditor1" not in station_view

    # a system administrator manages accounts, never cases
    assert world.client.get("/api/cases", headers=hs).json() == []
    world.make_case("officer1")
    assert world.client.get("/api/cases", headers=hs).json() == []
    judge = next(u for u in world.client.get("/api/users", headers=hs).json() if u["username"] == "krr.judge")
    r = world.client.patch(f"/api/users/{judge['id']}", headers=hs, json={"is_active": True, "rank": "high_court"})
    assert r.status_code == 200 and r.json()["rank"] == "high_court"
    assert world.client.patch(f"/api/users/{judge['id']}", headers=hs, json={"is_active": True, "rank": "station_head"}).status_code == 422


def test_tampering_raises_an_alert_for_the_people_responsible(world):
    world.station_district("CPS", "KRR")
    world.add_user("krr_judge", "judge", station=None, rank="district_court", district="KRR")
    world.add_user("elsewhere", "officer", station="NPS")
    case = world.make_case("officer1")
    doc = world.upload(case["id"], "officer1")
    assert world.client.get("/api/alerts", headers=world.h("officer1")).json()["unread"] == 0

    with world.app.state.session_factory() as db:  # someone with database access edits the stored file
        v = db.execute(select(DocumentVersion).where(DocumentVersion.document_id == doc["id"])).scalar_one()
        s = world.app.state.storage
        blob = bytearray(s.get(v.storage_key))
        blob[0] ^= 1
        s.put(v.storage_key, bytes(blob))
    world.client.get(f"/api/documents/{doc['id']}/versions/1/verify", headers=world.h("officer1"))

    a = world.client.get("/api/alerts", headers=world.h("officer1")).json()
    assert a["unread"] == 1 and a["items"][0]["action"] == "TAMPER_DETECTED" and a["items"][0]["case_id"] == case["id"]
    assert a["items"][0]["document_id"] == doc["id"]
    assert world.client.get("/api/alerts", headers=world.h("krr_judge")).json()["unread"] == 1  # the court sees it too
    assert world.client.get("/api/alerts", headers=world.h("elsewhere")).json()["unread"] == 0  # not their case
    assert world.client.get("/api/alerts", headers=world.h("auditor1")).json()["unread"] >= 1

    assert world.client.post("/api/alerts/seen", headers=world.h("officer1")).status_code == 204
    assert world.client.get("/api/alerts", headers=world.h("officer1")).json()["unread"] == 0
    assert world.client.get("/api/alerts", headers=world.h("krr_judge")).json()["unread"] == 1  # read state is per person

    d = world.client.get("/api/dashboard", headers=world.h("officer1")).json()
    assert d["cases"]["open"] == 1 and d["cases"]["by_stage"] == {"under_investigation": 1} and d["documents"] == 1
    assert d["alerts"][0]["action"] == "TAMPER_DETECTED"


def test_dashboard_lists_shares_about_to_expire(world):
    world.add_user("lab", "forensic", station=None)
    case = world.make_case("officer1")
    world.client.post(f"/api/cases/{case['id']}/shares", headers=world.h("officer1"), json={"user_id": world._uid("lab"), "days": 3})
    d = world.client.get("/api/dashboard", headers=world.h("officer1")).json()
    assert [(s["case_id"], s["username"]) for s in d["expiring_shares"]] == [(case["id"], "lab")]
