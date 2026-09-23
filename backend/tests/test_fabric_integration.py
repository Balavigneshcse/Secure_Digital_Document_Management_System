"""Integration tests against the REAL Hyperledger Fabric network (fabric/docker-compose.yml).

Skipped automatically when the network isn't running. The ledger is persistent, so every test uses fresh ids
and never depends on the ledger being empty.
"""
from __future__ import annotations

import concurrent.futures as cf
import hashlib
import uuid

import pytest
from fastapi.testclient import TestClient

from app.fabric_ledger import FabricLedger, LedgerError
from app.ledger import canonical, sha256_hex
from app.main import create_app
from conftest import FIR_TEXT, World

pytestmark = pytest.mark.fabric


def uid() -> int:
    return 10**9 + uuid.uuid4().int % 10**9


def doc_payload(**over) -> dict:
    p = {"document_uid": uuid.uuid4().hex, "document_id": uid(), "version_no": 1, "case_number": "TEST-1", "sha256": hashlib.sha256(uuid.uuid4().bytes).hexdigest(),
         "size": 5, "uploader_id": 1, "uploaded_at": "2026-01-01T00:00:00.000000Z", "prev_sha256": None}
    p.update(over)
    return p


@pytest.fixture(scope="module")
def fabric(base_settings):
    led = FabricLedger(base_settings.fabric_gateway_url, base_settings.fabric_gateway_key or "")
    try:
        led.status()
    except LedgerError as exc:
        pytest.skip(f"Fabric network not running: {exc}")
    return led


def test_anchor_is_a_committed_transaction_and_reads_back(fabric):
    p = doc_payload()
    b = fabric.anchor("DOC_VERSION", p)
    assert len(b.tx_id) == 64 and b.index >= 5 and b.payload == p
    assert b.payload_hash == sha256_hex(canonical(p)) and len(b.block_hash) == 64 and len(b.prev_hash) == 64

    got = fabric.get_by_tx(b.tx_id)
    assert got.payload == p and got.index == b.index and got.block_hash == b.block_hash and got.tx_id == b.tx_id
    assert fabric.verify_record(got)
    assert fabric.get_by_tx("0" * 64) is None
    assert fabric.latest("DOC_VERSION") is not None and fabric.latest("NO_SUCH_KIND") is None


def test_a_document_version_can_only_be_anchored_once(fabric):
    p = doc_payload()
    fabric.anchor("DOC_VERSION", p)
    with pytest.raises(LedgerError, match="already anchored"):
        fabric.anchor("DOC_VERSION", dict(p, sha256=hashlib.sha256(b"a different file").hexdigest()))  # the hash can't be swapped later


def test_chaincode_validates_what_it_records(fabric):
    def raw(kind, payload_json):
        return fabric._c.post("/anchor", json={"kind": kind, "payload_json": payload_json})

    assert "UPPER_SNAKE_CASE" in raw("lowercase", "{}").json()["error"]
    assert "JSON object" in raw("TEST_KIND", "[1,2]").json()["error"]
    assert "not valid JSON" in raw("TEST_KIND", "{nope").json()["error"]
    assert "hex sha256" in raw("DOC_VERSION", '{"document_uid":"%s","version_no":1,"sha256":"xyz"}' % ("a" * 32)).json()["error"]
    assert raw("TEST_KIND", "x" * 20000).status_code == 502  # over the payload size cap


def test_gateway_requires_its_key(base_settings):
    bad = FabricLedger(base_settings.fabric_gateway_url, "not-the-key")
    with pytest.raises(LedgerError, match="401"):
        bad.status()
    dead = FabricLedger("http://127.0.0.1:9", "k", timeout=2)
    with pytest.raises(LedgerError, match="unreachable"):
        dead.anchor("TEST_KIND", {"a": 1})


def test_concurrent_anchors_all_commit(fabric):
    run = uuid.uuid4().hex
    with cf.ThreadPoolExecutor(8) as ex:
        blocks = list(ex.map(lambda i: fabric.anchor("TEST_LOAD", {"n": i, "run": run}), range(16)))
    assert len({b.tx_id for b in blocks}) == 16
    assert all(fabric.get_by_tx(b.tx_id).payload["run"] == run for b in blocks)


def test_chain_verification_and_block_explorer(fabric):
    b = fabric.anchor("TEST_EXPLORER", {"x": uid()})
    v = fabric.verify_chain()
    assert v["ok"] is True and v["checked"] >= b.index + 1
    items, total = fabric.blocks(kind="TEST_EXPLORER", limit=200)
    assert any(i.tx_id == b.tx_id and i.payload == b.payload for i in items) and total >= 1
    everything, all_total = fabric.blocks(limit=200)
    assert all_total >= total and any(i.kind == "GENESIS" for i in fabric.blocks(kind="GENESIS")[0])
    st = fabric.status()
    assert st["backend"] == "fabric" and st["height"] >= b.index + 1 and st["channel"] == "sdmschannel"


# ---- the whole application on top of the real ledger -----------------------------------------------------
@pytest.fixture
def fworld(settings_factory, clock, fabric, base_settings):
    s = settings_factory(ledger_backend="fabric", fabric_gateway_url=base_settings.fabric_gateway_url,
                         fabric_gateway_key=base_settings.fabric_gateway_key)
    app = create_app(s)
    with TestClient(app) as client:
        w = World(app, client, clock)
        w.add_user("officer1", "officer")
        w.add_user("auditor1", "auditor")
        yield w


def test_upload_is_anchored_on_fabric_and_verifies(fworld):
    doc = fworld.upload(fworld.make_case()["id"])
    v = doc["versions"][0]
    assert len(v["ledger_tx_id"]) == 64 and v["ledger_block"] >= 5

    tx = fworld.client.get(f"/api/ledger/tx/{v['ledger_tx_id']}", headers=fworld.h("auditor1")).json()
    assert tx["kind"] == "DOC_VERSION" and tx["payload"]["sha256"] == v["sha256"] and tx["payload"]["document_uid"] == doc["uid"]
    assert "Ramesh" not in str(tx)                                       # no case content on the ledger

    ok = fworld.client.get(f"/api/documents/{doc['id']}/versions/1/verify", headers=fworld.h("officer1")).json()
    assert ok["status"] == "verified" and ok["ledger_block"] == v["ledger_block"]
    assert fworld.client.get(f"/api/documents/{doc['id']}/versions/1/download", headers=fworld.h("officer1")).content == FIR_TEXT

    chain = fworld.client.get("/api/ledger/verify", headers=fworld.h("auditor1")).json()
    assert chain["ok"] is True and chain["checked"] > v["ledger_block"]
    blocks = fworld.client.get("/api/ledger/blocks", headers=fworld.h("auditor1"), params={"kind": "DOC_VERSION", "limit": 200}).json()
    assert any(b["tx_id"] == v["ledger_tx_id"] for b in blocks["items"])
    health = fworld.client.get("/api/health").json()
    assert health["status"] == "ok" and health["ledger"] == {"backend": "fabric", "reachable": True}   # public: no topology
    st = fworld.client.get("/api/ledger/status", headers=fworld.h("auditor1")).json()
    assert st["backend"] == "fabric" and st["channel"] == "sdmschannel" and st["height"] > v["ledger_block"]
    assert fworld.client.get("/api/ledger/status", headers=fworld.h("officer1")).status_code == 403


def test_rewriting_the_database_hash_is_caught_by_the_real_ledger(fworld):
    from sqlalchemy import select

    from app.models import DocumentVersion

    doc = fworld.upload(fworld.make_case()["id"])
    with fworld.app.state.session_factory() as db:
        v = db.execute(select(DocumentVersion).where(DocumentVersion.document_id == doc["id"])).scalar_one()
        v.sha256 = hashlib.sha256(b"forged").hexdigest()
        db.commit()
    r = fworld.client.get(f"/api/documents/{doc['id']}/versions/1/download", headers=fworld.h("officer1"))
    assert r.status_code == 409 and any("ledger" in x for x in r.json()["detail"]["report"]["reasons"])


def test_audit_head_is_anchored_on_fabric_and_truncation_is_detected(fworld):
    from sqlalchemy import text

    fworld.upload(fworld.make_case()["id"])
    ha = fworld.h("auditor1")
    anchored = fworld.client.post("/api/audit/anchor", headers=ha).json()
    assert len(anchored["tx_id"]) == 64
    assert fworld.client.get("/api/audit/verify", headers=ha).json()["ok"] is True
    with fworld.app.state.engine.begin() as conn:                         # attacker deletes the newest audit rows
        conn.execute(text("DELETE FROM audit_log WHERE id >= :i"), {"i": anchored["audit_id"]})
    bad = fworld.client.get("/api/audit/verify", headers=ha).json()
    assert bad["ok"] is False and "anchored" in bad["reason"]


def test_ledger_outage_refuses_the_upload_and_stores_nothing(fworld):
    fworld.app.state.ledger = FabricLedger("http://127.0.0.1:9", "k", timeout=2)
    fworld.upload(fworld.make_case()["id"], expect=503)
    assert fworld.app.state.mongo.db["blobs.files"].count_documents({}) == 0
    assert fworld.app.state.mongo.doc_meta.count_documents({}) == 0
