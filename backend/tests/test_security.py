from __future__ import annotations

import socket
import struct
import threading

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.main import create_app
from app.models import Document
from conftest import PASSWORD, World

EICAR = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"


@pytest.fixture
def make_world(settings_factory, clock):
    """A World over an app with custom settings (rate limiting is off in the default fixtures)."""
    clients: list[TestClient] = []

    def make(**over) -> World:
        client = TestClient(create_app(settings_factory(**over)))
        client.__enter__()
        clients.append(client)
        w = World(client.app, client, clock)
        for name, role in (("officer1", "officer"), ("officer2", "officer"), ("auditor1", "auditor")):
            w.add_user(name, role)
        client.headers["X-Forwarded-For"] = "198.51.100.1"  # legitimate users, when a proxy is trusted
        return w

    yield make
    for c in clients:
        c.__exit__(None, None, None)


def _bad_login(w: World, ip: str, n: int = 1):
    return [w.client.post("/api/auth/login", headers={"X-Forwarded-For": ip}, json={"username": f"nobody{i}", "password": "wrong-password-1"})
            for i in range(n)]


# ---- rate limiting + client IP ------------------------------------------------------------------------
def test_login_is_rate_limited_per_client_ip_and_audited_once(make_world):
    w = make_world(rate_limit_enabled=True, login_attempts_per_minute=4, trusted_proxies="testclient")
    codes = [r.status_code for r in _bad_login(w, "203.0.113.9", 8)]
    assert codes == [401] * 4 + [429] * 4
    limited = w.client.post("/api/auth/login", headers={"X-Forwarded-For": "203.0.113.9"}, json={"username": "x", "password": "y"})
    assert int(limited.headers["retry-after"]) >= 1

    assert w.login("auditor1")                                         # a different client is unaffected
    alerts = [e for e in w.audit_actions(action="RATE_LIMITED")]
    assert len(alerts) == 1 and alerts[0]["ip"] == "203.0.113.9" and alerts[0]["outcome"] == "alert"   # 5 refusals, 1 entry


def test_mfa_endpoints_are_throttled_too(make_world):
    w = make_world(rate_limit_enabled=True, login_attempts_per_minute=3, trusted_proxies="testclient")
    r = w.client.post("/api/auth/login", json={"username": "officer1", "password": PASSWORD}).json()
    h = {"Authorization": f"Bearer {r['token']}"}
    codes = [w.client.post("/api/auth/mfa/enable", headers={**h, "X-Forwarded-For": "203.0.113.7"}, json={"code": "000000"}).status_code
             for _ in range(5)]
    assert codes[:3] != [429] * 3 and codes[-1] == 429


@pytest.mark.parametrize("trusted, xff, expected", [
    ("testclient", "1.2.3.4", "1.2.3.4"),                       # trusted proxy: believe its header
    ("testclient", "9.9.9.9, 1.2.3.4", "1.2.3.4"),               # client-prepended junk is ignored (rightmost untrusted hop wins)
    ("testclient,10.0.0.0/8", "1.2.3.4, 10.1.1.1", "1.2.3.4"),   # a chain of trusted proxies is skipped
    ("", "1.2.3.4", "testclient"),                               # no trusted proxy: header cannot be spoofed
    ("10.0.0.0/8", "1.2.3.4", "testclient"),                     # peer is not that proxy: header ignored
    ("testclient", "=cmd|' /C calc'!A0", "testclient"),          # not an address: never recorded
])
def test_client_ip_cannot_be_spoofed(make_world, trusted, xff, expected):
    w = make_world(trusted_proxies=trusted)
    w.client.post("/api/auth/login", headers={"X-Forwarded-For": xff}, json={"username": "ghost", "password": "wrong-password-1"})
    entry = w.audit_actions(actor="ghost")[0]
    assert entry["action"] == "LOGIN_FAILED" and entry["ip"] == expected


@pytest.mark.parametrize("xff, expected", [
    ("192.168.1.50", "192.168.1.50"),            # a LAN client shares the proxies' private range: kept, not skipped
    ("8.8.8.8, 192.168.1.50", "192.168.1.50"),   # an entry the client wrote further left is never read
    ("not-an-ip", "testclient"),                 # garbage is never recorded as an address
])
def test_proxy_hop_count_attributes_lan_clients_and_ignores_forged_entries(make_world, xff, expected):
    """The docker-compose setup: nginx on a private network, clients on private networks too."""
    w = make_world(trusted_proxies="testclient,192.168.0.0/16", trusted_proxy_hops=1)
    w.client.post("/api/auth/login", headers={"X-Forwarded-For": xff}, json={"username": "ghost", "password": "wrong-password-1"})
    assert w.audit_actions(actor="ghost")[0]["ip"] == expected


def test_change_password_is_rate_limited(make_world):
    w = make_world(rate_limit_enabled=True, login_attempts_per_minute=3, trusted_proxies="testclient", lockout_threshold=100)
    h = w.login("officer1")
    codes = [w.client.post("/api/auth/change-password", headers=h,
                           json={"current_password": "wrong-guess-123", "new_password": "N3w-Passw0rd-long"}).status_code
             for _ in range(5)]
    assert codes == [400] * 3 + [429] * 2


def test_uploads_are_throttled_per_user(make_world):
    w = make_world(rate_limit_enabled=True, upload_per_minute=2, trusted_proxies="testclient")
    cid = w.make_case("officer1")["id"]
    w.upload(cid), w.upload(cid)
    w.upload(cid, expect=429)
    other = w.make_case("officer2")["id"]
    w.upload(other, "officer2")                                          # another user has their own allowance


# ---- session refresh ----------------------------------------------------------------------------------------
def _claims(token: str) -> dict:
    return jwt.decode(token, options={"verify_signature": False})


def test_refresh_issues_a_new_token_and_keeps_the_session_start(world):
    h = world.h("officer1")
    old = h["Authorization"].split()[1]
    r = world.client.post("/api/auth/refresh", headers=h)
    assert r.status_code == 200 and r.json()["stage"] == "authenticated"
    new = r.json()["token"]
    assert _claims(new)["sat"] == _claims(old)["sat"]                    # absolute session start is preserved
    assert _claims(new)["exp"] >= _claims(old)["exp"]
    assert world.client.get("/api/auth/me", headers={"Authorization": f"Bearer {new}"}).status_code == 200


def test_a_session_cannot_be_refreshed_past_its_absolute_limit(world):
    h = world.h("officer1")
    world.app.state.settings.session_max_hours = 0
    r = world.client.post("/api/auth/refresh", headers=h)
    assert r.status_code == 401 and "maximum length" in r.json()["detail"]


def test_refresh_rejects_partial_revoked_and_unfinished_sessions(world):
    r = world.client.post("/api/auth/login", json={"username": "officer2", "password": PASSWORD}).json()
    assert world.client.post("/api/auth/refresh", headers={"Authorization": f"Bearer {r['token']}"}).status_code == 401  # password-only token
    h = world.h("officer1")
    assert world.client.post("/api/auth/logout", headers=h).status_code == 204
    assert world.client.post("/api/auth/refresh", headers=h).status_code == 401                                          # logged out
    world.add_user("newbie", "officer", must_change=True)
    assert world.client.post("/api/auth/refresh", headers=world.login("newbie")).status_code == 403                    # must change password first
    assert world.client.post("/api/auth/refresh").status_code == 401


# ---- antivirus (protocol-level fake of clamd) -----------------------------------------------------------
class FakeClamd:
    """Speaks clamd's INSTREAM protocol; flags the EICAR test string."""

    def __init__(self, mode: str = "scan"):
        self.mode, self.scanned = mode, 0
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(5)
        self.port = self.sock.getsockname()[1]
        threading.Thread(target=self._serve, daemon=True).start()

    def _read(self, c, n):
        buf = b""
        while len(buf) < n:
            part = c.recv(n - len(buf))
            if not part:
                raise EOFError
            buf += part
        return buf

    def _serve(self):
        while True:
            try:
                c, _ = self.sock.accept()
            except OSError:
                return
            try:
                assert self._read(c, 10) == b"zINSTREAM\0"
                data = b""
                while True:
                    (n,) = struct.unpack("!I", self._read(c, 4))
                    if n == 0:
                        break
                    data += self._read(c, n)
                self.scanned += 1
                if self.mode == "error":
                    c.sendall(b"INSTREAM size limit exceeded. ERROR\0")
                else:
                    c.sendall(b"stream: Eicar-Test-Signature FOUND\0" if b"EICAR-STANDARD-ANTIVIRUS-TEST-FILE" in data else b"stream: OK\0")
            except (EOFError, AssertionError, OSError):
                pass
            finally:
                c.close()

    def close(self):
        self.sock.close()


@pytest.fixture
def clamd():
    servers = []

    def make(mode="scan"):
        s = FakeClamd(mode)
        servers.append(s)
        return s

    yield make
    for s in servers:
        s.close()


def _nothing_stored(w: World):
    with w.app.state.session_factory() as db:
        assert db.scalar(select(func.count(Document.id))) == 0
    assert w.app.state.mongo.db["blobs.files"].count_documents({}) == 0 and w.app.state.mongo.doc_meta.count_documents({}) == 0


def test_clean_files_pass_and_infected_files_are_rejected_and_audited(world, clamd):
    from app.antivirus import ClamAV

    av = clamd()
    world.app.state.av = ClamAV("127.0.0.1", av.port)
    cid = world.make_case()["id"]
    world.upload(cid)                                                    # clean -> stored
    assert av.scanned == 1
    r = world.client.post(f"/api/cases/{cid}/documents", headers=world.h("officer1"), data={"title": "bad"},
                          files={"file": ("virus.txt", EICAR, "text/plain")})
    assert r.status_code == 422 and "Eicar-Test-Signature" in r.json()["detail"]
    alert = world.audit_actions(action="UPLOAD_REJECTED_MALWARE")[0]
    assert alert["outcome"] == "alert" and alert["detail"]["signature"] == "Eicar-Test-Signature" and alert["detail"]["filename"] == "virus.txt"
    with world.app.state.session_factory() as db:
        assert db.scalar(select(func.count(Document.id))) == 1           # only the clean one exists
    # a new version is scanned too
    doc_id = 1
    r = world.client.post(f"/api/documents/{doc_id}/versions", headers=world.h("officer1"), files={"file": ("v2.txt", EICAR, "text/plain")})
    assert r.status_code == 422


def test_unreachable_scanner_fails_open_or_closed_as_configured(world):
    from app.antivirus import ClamAV

    dead = socket.socket()
    dead.bind(("127.0.0.1", 0))
    port = dead.getsockname()[1]
    dead.close()                                                         # nothing listens there now
    world.app.state.av = ClamAV("127.0.0.1", port, timeout=2)
    cid = world.make_case()["id"]

    world.app.state.settings.clamav_required = False
    world.upload(cid)                                                    # best effort: filing continues

    world.app.state.settings.clamav_required = True
    r = world.client.post(f"/api/cases/{cid}/documents", headers=world.h("officer1"), data={"title": "x"},
                          files={"file": ("a.txt", b"hello", "text/plain")})
    assert r.status_code == 503 and "scanner" in r.json()["detail"]


def test_scanner_error_reply_is_not_treated_as_clean(world, clamd):
    from app.antivirus import ClamAV

    world.app.state.av = ClamAV("127.0.0.1", clamd("error").port)
    world.app.state.settings.clamav_required = True
    r = world.client.post(f"/api/cases/{world.make_case()['id']}/documents", headers=world.h("officer1"), data={"title": "x"},
                          files={"file": ("a.txt", b"hello", "text/plain")})
    assert r.status_code == 503
    _nothing_stored(world)
