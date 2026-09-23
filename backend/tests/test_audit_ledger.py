from __future__ import annotations

from sqlalchemy import text


def _exec(world, sql, **params):
    with world.app.state.engine.begin() as conn:
        conn.execute(text(sql), params)


def _activity(world):
    case = world.make_case()
    doc = world.upload(case["id"])
    world.client.get(f"/api/documents/{doc['id']}/versions/1/download", headers=world.h("officer1"))
    return case, doc


def test_every_action_is_attributed_in_the_audit_trail(world):
    case, doc = _activity(world)
    world.client.get(f"/api/cases/{case['id']}", headers=world.h("officer1"))
    world.client.get("/api/search", headers=world.h("officer1"), params={"q": "theft"})
    items = world.audit_actions()
    actions = [e["action"] for e in items]
    for expected in ("LOGIN_SUCCESS", "MFA_ENROLLED", "CASE_CREATED", "DOCUMENT_UPLOADED", "DOCUMENT_DOWNLOADED",
                     "CASE_VIEWED", "SEARCH"):
        assert expected in actions, expected
    up = next(e for e in items if e["action"] == "DOCUMENT_UPLOADED")
    assert up["actor_username"] == "officer1" and up["actor_role"] == "officer"
    assert up["case_number"] == case["case_number"] and up["detail"]["sha256"] and up["ip"]


def test_audit_is_auditor_only_and_filterable(world):
    _activity(world)
    assert world.client.get("/api/audit", headers=world.h("officer1")).status_code == 403
    only = world.audit_actions(actor="officer1", action="DOCUMENT_UPLOADED")
    assert len(only) == 1
    assert world.audit_actions(case_number="CR-NOPE") == []


def test_audit_chain_verifies_then_detects_edit(world):
    _activity(world)
    ha = world.h("auditor1")
    ok = world.client.get("/api/audit/verify", headers=ha).json()
    assert ok["ok"] is True and ok["checked"] > 5

    _exec(world, "UPDATE audit_log SET actor_username='someone_else' WHERE action='DOCUMENT_DOWNLOADED'")
    bad = world.client.get("/api/audit/verify", headers=ha).json()
    assert bad["ok"] is False and "altered" in bad["reason"] and bad["broken_at"]


def test_audit_chain_detects_deleted_row(world):
    _activity(world)
    _exec(world, "DELETE FROM audit_log WHERE action='DOCUMENT_UPLOADED'")
    bad = world.client.get("/api/audit/verify", headers=world.h("auditor1")).json()
    assert bad["ok"] is False and "link" in bad["reason"]


def test_ledger_anchor_catches_tail_truncation(world):
    _activity(world)
    ha = world.h("auditor1")
    anchored = world.client.post("/api/audit/anchor", headers=ha).json()
    assert anchored["audit_id"] and anchored["tx_id"]
    assert world.client.get("/api/audit/verify", headers=ha).json()["ok"] is True

    # Attacker drops the newest entries (chain alone would still look consistent).
    _exec(world, "DELETE FROM audit_log WHERE id >= :i", i=anchored["audit_id"])
    bad = world.client.get("/api/audit/verify", headers=ha).json()
    assert bad["ok"] is False and "anchored" in bad["reason"]


def test_ledger_chain_verifies_then_detects_tamper(world):
    _activity(world)
    ha = world.h("auditor1")
    good = world.client.get("/api/ledger/verify", headers=ha).json()
    assert good["ok"] is True and good["checked"] >= 2  # genesis + document block

    world.app.state.ledger._tamper(1, ts="2001-01-01T00:00:00.000000Z")
    bad = world.client.get("/api/ledger/verify", headers=ha).json()
    assert bad["ok"] is False and bad["broken_at"] == 1

    # ... and the verification result itself is audited as an alert.
    assert any(e["action"] == "LEDGER_VERIFIED" and e["outcome"] == "alert" for e in world.audit_actions())


def test_ledger_blocks_listing(world):
    _activity(world)
    r = world.client.get("/api/ledger/blocks", headers=world.h("auditor1"), params={"kind": "DOC_VERSION"}).json()
    assert r["total"] == 1 and r["items"][0]["kind"] == "DOC_VERSION"
    assert world.client.get("/api/ledger/tx/deadbeef", headers=world.h("auditor1")).status_code == 404


def test_export_csv_neutralises_spreadsheet_formulas(world):
    world.client.post("/api/auth/login", json={"username": "=HYPERLINK(\"http://evil\")", "password": "x"})
    r = world.client.get("/api/audit/export", headers=world.h("auditor1"))
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    lines = r.text.splitlines()
    assert lines[0].startswith("id,ts,actor_username")
    assert "'=hyperlink" in r.text.lower()
    assert not any(l.split(",")[2].startswith("=") for l in lines[1:] if l.count(",") > 3)
    assert any(e["action"] == "AUDIT_EXPORTED" for e in world.audit_actions())


def test_concurrent_writes_keep_a_single_unbroken_chain(world):
    import concurrent.futures as cf

    world.make_case()
    h = world.h("officer1")
    with cf.ThreadPoolExecutor(8) as ex:
        results = list(ex.map(lambda i: world.client.post("/api/cases", headers=h, json={"title": f"C{i}"}).status_code, range(16)))
    assert results == [201] * 16
    assert world.client.get("/api/audit/verify", headers=world.h("auditor1")).json()["ok"] is True
