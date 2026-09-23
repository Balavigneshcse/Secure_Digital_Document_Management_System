from __future__ import annotations


def _user_id(world, username):
    users = world.client.get("/api/users", headers=world.h("admin1")).json()
    return next(u["id"] for u in users if u["username"] == username)


def test_officer_creates_case_and_is_auto_assigned(world):
    case = world.make_case("officer1")
    assert case["case_number"].startswith("CR-") and "-CPS-" in case["case_number"]
    assert [a["username"] for a in case["assignees"]] == ["officer1"]
    assert case["parties"] == [{"name": "Ramesh Kumar", "role": "complainant"}]
    assert case["document_count"] == 0


def test_unassigned_officer_gets_404_and_denial_is_audited(world):
    case = world.make_case("officer1")
    doc = world.upload(case["id"])
    h2 = world.h("officer2")
    assert world.client.get(f"/api/cases/{case['id']}", headers=h2).status_code == 404
    assert world.client.get(f"/api/cases/{case['id']}/documents", headers=h2).status_code == 404
    assert world.client.get(f"/api/documents/{doc['id']}", headers=h2).status_code == 404
    assert world.client.get(f"/api/documents/{doc['id']}/versions/1/download", headers=h2).status_code == 404
    assert world.client.get("/api/cases", headers=h2).json() == []

    denied = world.audit_actions(outcome="denied")
    assert len(denied) >= 4 and all(e["actor_username"] == "officer2" for e in denied)


def test_admin_sees_case_metadata_but_never_document_content(world):
    case = world.make_case("officer1")
    doc = world.upload(case["id"])
    ha = world.h("admin1")
    listed = world.client.get("/api/cases", headers=ha).json()
    assert [c["id"] for c in listed] == [case["id"]]
    assert listed[0]["document_count"] is None  # count of content hidden too

    assert world.client.get(f"/api/cases/{case['id']}/documents", headers=ha).status_code == 403
    assert world.client.get(f"/api/documents/{doc['id']}", headers=ha).status_code == 403
    assert world.client.get(f"/api/documents/{doc['id']}/versions/1/download", headers=ha).status_code == 403
    r = world.client.post(f"/api/cases/{case['id']}/documents", headers=ha, data={"title": "x"},
                          files={"file": ("a.txt", b"hello", "text/plain")})
    assert r.status_code == 403


def test_auditor_has_no_case_or_document_access(world):
    case = world.make_case("officer1")
    doc = world.upload(case["id"])
    ha = world.h("auditor1")
    assert world.client.get("/api/cases", headers=ha).status_code == 403
    assert world.client.get(f"/api/documents/{doc['id']}", headers=ha).status_code == 403
    assert world.client.get(f"/api/documents/{doc['id']}/versions/1/download", headers=ha).status_code == 403
    assert world.client.get("/api/search", headers=ha).status_code == 403
    assert world.client.get("/api/users", headers=ha).status_code == 403


def test_officer_cannot_touch_admin_or_audit_endpoints(world):
    h = world.h("officer1")
    assert world.client.get("/api/users", headers=h).status_code == 403
    assert world.client.post("/api/users", headers=h, json={"username": "x.y", "full_name": "X", "password": "Passw0rd-long"}).status_code == 403
    assert world.client.get("/api/audit", headers=h).status_code == 403
    assert world.client.get("/api/ledger/blocks", headers=h).status_code == 403
    assert world.client.post("/api/audit/anchor", headers=h).status_code == 403


def test_admin_assigns_and_unassigns_officer(world):
    case = world.make_case("officer1")
    ha, h2 = world.h("admin1"), world.h("officer2")
    assert world.client.get(f"/api/cases/{case['id']}", headers=h2).status_code == 404

    r = world.client.post(f"/api/cases/{case['id']}/assignments", headers=ha, json={"user_id": _user_id(world, "officer2")})
    assert r.status_code == 200 and {a["username"] for a in r.json()["assignees"]} == {"officer1", "officer2"}
    assert world.client.get(f"/api/cases/{case['id']}", headers=h2).status_code == 200
    assert world.client.post(f"/api/cases/{case['id']}/assignments", headers=ha,
                             json={"user_id": _user_id(world, "officer2")}).status_code == 409

    r = world.client.delete(f"/api/cases/{case['id']}/assignments/{_user_id(world, 'officer2')}", headers=ha)
    assert r.status_code == 200
    assert world.client.get(f"/api/cases/{case['id']}", headers=h2).status_code == 404


def test_admin_cannot_cross_station_boundaries(world):
    world.add_user("admin_b", "admin", station="OTH")
    world.add_user("officer_b", "officer", station="OTH")
    case = world.make_case("officer1")

    hb = world.h("admin_b")
    assert world.client.get("/api/cases", headers=hb).json() == []
    assert world.client.get(f"/api/cases/{case['id']}", headers=hb).status_code == 404
    other_officer = next(u["id"] for u in world.client.get("/api/users", headers=hb).json() if u["username"] == "officer_b")
    # Cannot assign another station's officer to our case, nor manage their accounts.
    ha = world.h("admin1")
    assert world.client.post(f"/api/cases/{case['id']}/assignments", headers=ha, json={"user_id": other_officer}).status_code == 400
    assert world.client.patch(f"/api/users/{other_officer}", headers=ha, json={"is_active": False}).status_code == 404
    assert world.client.post(f"/api/users/{other_officer}/reset-mfa", headers=ha).status_code == 404


def test_admin_creates_officer_who_must_change_password(world):
    ha = world.h("admin1")
    r = world.client.post("/api/users", headers=ha, json={"username": "new.officer", "full_name": "New Officer", "password": "Temp0rary-Pass"})
    assert r.status_code == 201 and r.json()["must_change_password"] is True and r.json()["role"] == "officer"
    assert world.client.post("/api/users", headers=ha, json={"username": "new.officer", "full_name": "Dup", "password": "Temp0rary-Pass"}).status_code == 409
    assert world.client.post("/api/users", headers=ha, json={"username": "weak.one", "full_name": "W", "password": "abc"}).status_code == 400
    # role escalation attempt is rejected by validation
    assert world.client.post("/api/users", headers=ha, json={"username": "sneaky", "full_name": "S", "password": "Temp0rary-Pass", "role": "auditor"}).status_code == 422


def test_admin_reset_mfa_forces_reenrolment(world):
    world.login("officer1")
    ha = world.h("admin1")
    uid = _user_id(world, "officer1")
    assert world.client.post(f"/api/users/{uid}/reset-mfa", headers=ha).status_code == 200
    r = world.client.post("/api/auth/login", json={"username": "officer1", "password": "Str0ng-Passw0rd!"})
    assert r.json()["stage"] == "mfa_setup_required"


def test_admin_can_create_case_and_assign_officers(world):
    ha = world.h("admin1")
    r = world.client.post("/api/cases", headers=ha, json={"title": "Fraud", "officer_ids": [_user_id(world, "officer2")]})
    assert r.status_code == 201
    assert [a["username"] for a in r.json()["assignees"]] == ["officer2"]
    assert world.client.get(f"/api/cases/{r.json()['id']}", headers=world.h("officer2")).status_code == 200
    # officers may not hand out assignments at creation
    r = world.client.post("/api/cases", headers=world.h("officer1"), json={"title": "X", "officer_ids": [_user_id(world, "officer2")]})
    assert r.status_code == 403
