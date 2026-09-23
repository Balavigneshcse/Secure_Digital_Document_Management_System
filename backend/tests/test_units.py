from __future__ import annotations

import io

import numpy as np
import pytest
from conftest import PASSWORD
from cryptography.exceptions import InvalidTag
from fastapi.testclient import TestClient

from app import crypto, docstore
from app.ai.stub import StubAI
from app.ledger import MemoryLedger, canonical
from app.main import create_app
from app.security import hash_password, password_problem, verify_password
from app.storage import GridFSStorage


def test_password_hashing_roundtrip_and_salting():
    a, b = hash_password("Correct-Horse-9"), hash_password("Correct-Horse-9")
    assert a != b and verify_password("Correct-Horse-9", a) and not verify_password("wrong", a)
    assert not verify_password("x", "garbage")


def test_password_policy():
    assert password_problem("short1") and password_problem("onlyletterslong") and password_problem("12345678901")
    assert password_problem("officer1-Password9", "officer1")
    assert password_problem("Sufficient-Pass9", "bob") is None


def test_envelope_encryption_binds_ciphertext_to_its_key():
    kek = b"k" * 32
    blob, wrapped = crypto.encrypt_file(kek, b"secret evidence", "a" * 32)
    assert crypto.decrypt_file(kek, blob, wrapped, "a" * 32) == b"secret evidence"
    with pytest.raises(InvalidTag):
        crypto.decrypt_file(kek, blob, wrapped, "b" * 32)  # moved under another storage key
    with pytest.raises(InvalidTag):
        crypto.decrypt_file(b"z" * 32, blob, wrapped, "a" * 32)  # wrong KEK
    with pytest.raises(InvalidTag):
        crypto.decrypt_file(kek, blob[:-1] + bytes([blob[-1] ^ 1]), wrapped, "a" * 32)
    # same plaintext never yields the same ciphertext
    assert crypto.encrypt_file(kek, b"secret evidence", "a" * 32)[0] != blob


def test_sealed_json_and_blind_index():
    kek = b"k" * 32
    tok = crypto.seal_json(kek, {"text": "witness Anita Sharma"}, b"1:1")
    assert crypto.open_json(kek, tok, b"1:1") == {"text": "witness Anita Sharma"}
    with pytest.raises(InvalidTag):
        crypto.open_json(kek, tok, b"1:2")
    idx = crypto.blind_tokens(kek, "Witness ANITA sharma, Section 379!")
    assert crypto.blind_tokens(kek, "anita") [0] in idx           # case-insensitive whole word
    assert crypto.blind_tokens(kek, "anit") [0] not in idx        # no substring matching
    assert crypto.blind_tokens(b"o" * 32, "anita")[0] not in idx  # only the key holder can test membership
    assert all("anita" not in t for t in idx)


def test_tokenizer_keeps_indic_words_whole():
    assert crypto.tokenize("प्राथमिकी दर्ज की गई") >= {"प्राथमिकी", "दर्ज", "गई"}
    assert crypto.tokenize("காவல் நிலையம்") == {"காவல்", "நிலையம்"}
    assert crypto.tokenize("a b IPC-379 x_y") == {"ipc", "379"}  # 1-char tokens and punctuation dropped


def test_memory_ledger_chain():
    led = MemoryLedger()
    b1, b2 = led.anchor("X", {"a": 1}), led.anchor("X", {"a": 2})
    assert b2.prev_hash == b1.block_hash and b2.index == b1.index + 1
    assert led.verify_chain()["ok"] and led.get_by_tx(b2.tx_id).payload == {"a": 2}
    assert led.latest("X").tx_id == b2.tx_id and led.blocks(kind="X")[1] == 2
    led._tamper(1, payload={"a": 999})
    assert not led.verify_chain()["ok"] and not led.verify_record(led.get_by_tx(b1.tx_id))


def test_canonical_json_is_order_independent():
    assert canonical({"b": 1, "a": [2, 1]}) == canonical({"a": [2, 1], "b": 1})


def test_gridfs_storage(app):
    s: GridFSStorage = app.state.storage
    key = "ab" * 16
    assert not s.exists(key)
    s.put(key, b"ciphertext")
    assert s.exists(key) and s.get(key) == b"ciphertext"
    s.put(key, b"replaced")
    assert s.get(key) == b"replaced" and app.state.mongo.db["blobs.files"].count_documents({}) == 1
    s.delete(key)
    assert not s.exists(key)
    with pytest.raises(FileNotFoundError):
        s.get(key)
    with pytest.raises(ValueError):
        s.put("../../etc/passwd", b"x")


def test_semantic_ranking_is_scoped_to_the_keys_it_is_given(app):
    m, kek = app.state.mongo, app.state.kek
    unit = lambda *v: list(np.array(v, dtype="float32") / np.linalg.norm(v))  # noqa: E731
    for i, vec in enumerate([unit(1, 0, 0), unit(0.9, 0.1, 0), unit(0, 1, 0), unit(0, 0, 1)], start=1):
        docstore.put_meta(m, kek, document_id=i, version_no=1, case_number="C", case_id=1, uploaded_at="t",
                          doc_type="fir", doc_confidence=0.9, provider="t", tags=[], content={"ocr_text": f"doc {i}"}, embedding=vec)
    top = docstore.semantic_top(m, ["1:1", "2:1", "3:1", "4:1"], unit(1, 0, 0), k=3)
    assert [k for k, _ in top] == ["1:1", "2:1"] and top[0][1] > top[1][1] > 0.9  # unrelated docs fall under min_score
    # a caller who may only see doc 3 can never get doc 1 back, however similar
    assert [k for k, _ in docstore.semantic_top(m, ["3:1"], unit(1, 0, 0), k=5, min_score=-1)] == ["3:1"]
    assert docstore.semantic_top(m, [], unit(1, 0, 0)) == [] and docstore.semantic_top(m, ["1:1"], []) == []


def test_stub_classifier_examples():
    ai = StubAI()
    r = ai.process("lab.txt", "text/plain", b"Forensic laboratory report: DNA and fingerprint analysis of exhibit 4. Received 02/01/2026.")
    assert r.doc_type == "forensic_report" and "02/01/2026" in r.entities["dates"] and r.embedding is None
    assert ai.process("x.txt", "text/plain", b"nothing recognisable here").doc_type == "other"
    assert ai.process("a.txt", "text/plain", b"hello").text == "hello"
    assert ai.process("a.pdf", "application/pdf", b"%PDF-broken").text == ""  # unparsable -> empty, not a crash
    assert ai.process("w.txt", "text/plain", b"Warrant of arrest issued against the accused").doc_type == "arrest_warrant"


def test_external_ai_url_without_a_key_is_a_startup_error(settings_factory):
    with pytest.raises(ValueError, match="SDMS_AI_SERVICE_KEY"):
        create_app(settings_factory(ai_service_url="http://ai:9000"))


def test_settings_require_postgres_mongo_and_a_gateway_key(base_settings):
    from app.config import Settings

    with pytest.raises(ValueError, match="PostgreSQL"):
        Settings(database_url="sqlite:///x.db", mongo_url="mongodb://localhost", ledger_backend="memory")
    with pytest.raises(ValueError, match="MongoDB"):
        Settings(database_url="postgresql+psycopg://u:p@h/db", mongo_url="", ledger_backend="memory")
    with pytest.raises(ValueError, match="GATEWAY_KEY"):
        Settings(database_url="postgresql+psycopg://u:p@h/db", mongo_url="mongodb://h", ledger_backend="fabric", fabric_gateway_key=None)


def test_cli_bootstraps_accounts_from_a_piped_password(settings_factory, monkeypatch):
    from app import cli

    s = settings_factory()
    monkeypatch.setenv("SDMS_DATABASE_URL", s.database_url)
    monkeypatch.setenv("SDMS_MONGO_URL", s.mongo_url)
    monkeypatch.setenv("SDMS_LEDGER_BACKEND", "memory")
    assert cli.main(["create-station", "--code", "cps", "--name", "Central"]) == 0

    monkeypatch.setattr("sys.stdin", io.StringIO("Sup3r-Secret-Pw1\n"))  # not a TTY -> read from stdin
    assert cli.main(["create-user", "--username", "jdoe", "--full-name", "J Doe", "--role", "admin", "--station-code", "cps"]) == 0
    monkeypatch.setattr("sys.stdin", io.StringIO("short\n"))
    assert cli.main(["create-user", "--username", "weak", "--full-name", "W", "--role", "admin", "--station-code", "cps"]) == 2
    assert cli.main(["create-user", "--username", "nost", "--full-name", "N", "--role", "officer"]) == 2

    # The account it made can start a login and is pushed into MFA enrolment.
    with TestClient(create_app(s)) as c:
        r = c.post("/api/auth/login", json={"username": "jdoe", "password": "Sup3r-Secret-Pw1"})
        assert r.status_code == 200 and r.json()["stage"] == "mfa_setup_required"
        assert c.post("/api/auth/login", json={"username": "weak", "password": "short"}).status_code == 401


def test_cli_reset_mfa_recovers_an_auditor_and_is_audited(world, monkeypatch, capsys):
    """A station admin can only reset officers, so a lost auditor phone needs the operator's CLI."""
    from app import cli

    s = world.app.state.settings
    monkeypatch.setenv("SDMS_DATABASE_URL", s.database_url)
    monkeypatch.setenv("SDMS_MONGO_URL", s.mongo_url)
    monkeypatch.setenv("SDMS_LEDGER_BACKEND", "memory")
    old = world.h("auditor1")
    assert world.client.get("/api/audit", headers=old).status_code == 200

    assert cli.main(["reset-mfa", "--username", "nobody"]) == 1                    # unknown user: refuses, changes nothing
    assert cli.main(["reset-mfa", "--username", "auditor1"]) == 0
    assert "enrol a new one" in capsys.readouterr().out

    assert world.client.get("/api/audit", headers=old).status_code == 401          # every existing session was signed out
    r = world.client.post("/api/auth/login", json={"username": "auditor1", "password": PASSWORD})
    assert r.status_code == 200 and r.json()["stage"] == "mfa_setup_required"      # password still needed; authenticator is new

    world.secrets.pop("auditor1"), world._headers.pop("auditor1")
    entries = world.audit_actions(action="MFA_RESET")                              # (world.h enrols the new authenticator first)
    assert any(e["actor_username"] == "cli" and e["detail"]["username"] == "auditor1" for e in entries)


def test_api_docs_are_disabled_by_default_and_opt_in(settings_factory):
    off, on = create_app(settings_factory()), create_app(settings_factory(enable_docs=True))
    with TestClient(off) as c:
        assert c.get("/docs").status_code == 404 and c.get("/openapi.json").status_code == 404
    with TestClient(on) as c:
        assert c.get("/docs").status_code == 200 and c.get("/openapi.json").status_code == 200


def test_security_headers_and_health(app):
    with TestClient(app) as c:
        r = c.get("/api/health")
        assert r.headers["x-content-type-options"] == "nosniff"
        assert r.headers["cache-control"] == "no-store" and "default-src 'none'" in r.headers["content-security-policy"]
        assert r.json()["status"] == "ok" and r.json()["ledger"] == {"backend": "memory", "reachable": True}
