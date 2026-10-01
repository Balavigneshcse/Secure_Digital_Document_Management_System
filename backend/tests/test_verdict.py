"""A district/high court judge records the final verdict: filed as a tamper-evident document, case closed, immutable."""
from __future__ import annotations

REASONS = "The prosecution proved the burglary beyond reasonable doubt on the forensic and witness evidence."


def _setup(world):
    world.station_district("CPS", "KRR")
    world.add_user("krr_judge", "judge", station=None, rank="district_court", district="KRR")
    return world.make_case("officer1")


def _verdict(world, case_id, user="krr_judge", **over):
    body = {"outcome": "convicted", "reasoning": REASONS, "sentence": "3 years rigorous imprisonment"}
    body.update(over)
    return world.client.post(f"/api/cases/{case_id}/verdict", headers=world.h(user), json=body)


def test_judge_records_verdict_which_is_anchored_audited_and_closes_the_case(world):
    case = _setup(world)
    r = _verdict(world, case["id"])
    assert r.status_code == 201, r.text
    doc = r.json()
    assert doc["doc_type"] == "judgment" and doc["versions"][0]["ledger_tx_id"]

    assert world.client.get(f"/api/cases/{case['id']}", headers=world.h("officer1")).json()["status"] == "closed"
    # officer and judge can both read it; it verifies against the ledger
    v = doc["versions"][0]["version_no"]
    for who in ("officer1", "krr_judge"):
        assert world.client.get(f"/api/documents/{doc['id']}/versions/{v}/download", headers=world.h(who)).status_code == 200
    assert world.client.get(f"/api/documents/{doc['id']}/versions/{v}/verify", headers=world.h("auditor1")).json()["status"] == "verified"
    body = world.client.get(f"/api/documents/{doc['id']}/versions/{v}/download", headers=world.h("officer1")).text
    assert "CONVICTED" in body and REASONS in body and case["case_number"] in body
    assert "VERDICT_RECORDED" in {a["action"] for a in world.audit_actions()}


def test_only_one_verdict_per_case(world):
    case = _setup(world)
    assert _verdict(world, case["id"]).status_code == 201
    assert _verdict(world, case["id"], outcome="acquitted").status_code == 409


def test_verdict_cannot_be_amended_or_relabelled_by_the_officer(world):
    case = _setup(world)
    doc = _verdict(world, case["id"]).json()
    r = world.client.post(f"/api/documents/{doc['id']}/versions", headers=world.h("officer1"),
                          data={"change_note": "edit"}, files={"file": ("v.txt", b"ACQUITTED, all charges dropped", "text/plain")})
    assert r.status_code == 403
    r = world.client.post(f"/api/documents/{doc['id']}/classification-feedback", headers=world.h("officer1"),
                          json={"correct_type": "other"})
    assert r.status_code == 403


def test_only_judge_with_jurisdiction_can_record_a_verdict(world):
    case = _setup(world)
    world.add_user("share_judge", "judge", station=None)  # rank=officer: read-only, per-case share
    world.add_user("forensic1", "forensic", station=None)
    world.add_user("other_judge", "judge", station=None, rank="district_court", district="CHN")
    sid = world.client.get("/api/users/reviewers", headers=world.h("officer1")).json()
    share = next(u["id"] for u in sid if u["username"] == "share_judge")
    assert world.client.post(f"/api/cases/{case['id']}/shares", headers=world.h("officer1"), json={"user_id": share}).status_code == 201

    assert _verdict(world, case["id"], "officer1").status_code == 403       # wrong role
    assert _verdict(world, case["id"], "forensic1").status_code == 403
    assert _verdict(world, case["id"], "share_judge").status_code == 403    # can read, cannot decide
    assert _verdict(world, case["id"], "other_judge").status_code == 404    # other district: case not even visible
    assert world.client.get(f"/api/cases/{case['id']}", headers=world.h("officer1")).json()["status"] == "open"


def test_verdict_validation(world):
    case = _setup(world)
    assert _verdict(world, case["id"], reasoning="too short").status_code == 422
    assert _verdict(world, case["id"], outcome="hanged").status_code == 422
