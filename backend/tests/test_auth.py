from __future__ import annotations

import pyotp

from conftest import PASSWORD


def test_unknown_user_and_wrong_password_look_identical(world):
    a = world.client.post("/api/auth/login", json={"username": "nobody", "password": "whatever123"})
    b = world.client.post("/api/auth/login", json={"username": "officer1", "password": "wrong-password1"})
    assert a.status_code == b.status_code == 401
    assert a.json() == b.json()


def test_full_login_requires_mfa_and_partial_tokens_grant_nothing(world):
    r = world.client.post("/api/auth/login", json={"username": "officer1", "password": PASSWORD})
    assert r.json()["stage"] == "mfa_setup_required"
    partial = {"Authorization": f"Bearer {r.json()['token']}"}
    # A password-only token must not open any real endpoint.
    assert world.client.get("/api/cases", headers=partial).status_code == 401
    assert world.client.get("/api/auth/me", headers=partial).status_code == 401

    h = world.login("officer1")
    me = world.client.get("/api/auth/me", headers=h).json()
    assert me["username"] == "officer1" and me["totp_enabled"] is True

    # Second login now demands the code rather than re-enrolment.
    r = world.client.post("/api/auth/login", json={"username": "officer1", "password": PASSWORD})
    assert r.json()["stage"] == "mfa_required"


def test_wrong_totp_rejected(world):
    world.login("officer1")
    r = world.client.post("/api/auth/login", json={"username": "officer1", "password": PASSWORD})
    tok = {"Authorization": f"Bearer {r.json()['token']}"}
    assert world.client.post("/api/auth/mfa/verify", headers=tok, json={"code": "000000"}).status_code == 401
    assert world.client.post("/api/auth/mfa/verify", headers=tok, json={"code": "abcdef"}).status_code == 401


def test_totp_code_cannot_be_replayed(world):
    world.login("officer1")
    world.clock.advance(30)
    code = pyotp.TOTP(world.secrets["officer1"]).generate_otp(int(world.clock() // 30))

    def attempt():
        r = world.client.post("/api/auth/login", json={"username": "officer1", "password": PASSWORD})
        tok = {"Authorization": f"Bearer {r.json()['token']}"}
        return world.client.post("/api/auth/mfa/verify", headers=tok, json={"code": code}).status_code

    assert attempt() == 200
    assert attempt() == 401  # same code, same time-step


def test_account_locks_after_repeated_failures(world):
    for _ in range(5):
        world.client.post("/api/auth/login", json={"username": "officer2", "password": "bad-password-1"})
    r = world.client.post("/api/auth/login", json={"username": "officer2", "password": PASSWORD})
    assert r.status_code == 423  # even the right password is refused while locked
    actions = {e["action"] for e in world.audit_actions()}
    assert {"LOGIN_FAILED", "ACCOUNT_LOCKED", "LOGIN_BLOCKED"} <= actions

    # Admin can unlock.
    uid = next(u["id"] for u in world.client.get("/api/users", headers=world.h("admin1")).json() if u["username"] == "officer2")
    assert world.client.post(f"/api/users/{uid}/unlock", headers=world.h("admin1")).status_code == 200
    assert world.client.post("/api/auth/login", json={"username": "officer2", "password": PASSWORD}).status_code == 200


def test_forced_password_change(world):
    world.add_user("newcomer", "officer", must_change=True)
    h = world.login("newcomer")
    assert world.client.get("/api/cases", headers=h).status_code == 403
    assert world.client.get("/api/auth/me", headers=h).json()["must_change_password"] is True

    weak = world.client.post("/api/auth/change-password", headers=h, json={"current_password": PASSWORD, "new_password": "short"})
    assert weak.status_code == 400
    ok = world.client.post("/api/auth/change-password", headers=h,
                           json={"current_password": PASSWORD, "new_password": "An0ther-Str0ng-One"})
    assert ok.status_code == 200
    new_h = {"Authorization": f"Bearer {ok.json()['token']}"}
    assert world.client.get("/api/cases", headers=new_h).status_code == 200
    assert world.client.get("/api/cases", headers=h).status_code == 401  # old session revoked


def test_logout_and_deactivation_revoke_tokens(world):
    h = world.login("officer2")
    assert world.client.post("/api/auth/logout", headers=h).status_code == 204
    assert world.client.get("/api/cases", headers=h).status_code == 401

    h1 = world.login("officer1")
    uid = next(u["id"] for u in world.client.get("/api/users", headers=world.h("admin1")).json() if u["username"] == "officer1")
    assert world.client.patch(f"/api/users/{uid}", headers=world.h("admin1"), json={"is_active": False}).status_code == 200
    assert world.client.get("/api/cases", headers=h1).status_code == 401
    assert world.client.post("/api/auth/login", json={"username": "officer1", "password": PASSWORD}).status_code == 401


def test_no_token_and_garbage_token(world):
    assert world.client.get("/api/cases").status_code == 401
    assert world.client.get("/api/cases", headers={"Authorization": "Bearer not.a.jwt"}).status_code == 401
