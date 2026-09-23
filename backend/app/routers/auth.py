from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select

from .. import audit
from ..crypto import decrypt_field, encrypt_field
from ..db import utcnow, utcnow_plus
from ..deps import DbSession, access_user, access_user_pw, client_ip, stage_user
from ..models import User
from ..netutil import RateLimited, enforce
from ..schemas import ChangePasswordIn, CodeIn, LoginIn, MfaSetupOut, StageTokenOut, UserOut
from ..security import (
    DUMMY_HASH, hash_password, make_token, new_totp_secret, password_problem, totp_uri, verify_password, verify_totp,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])

GENERIC_FAIL = "Invalid username or password"


def user_out(u: User) -> UserOut:
    return UserOut(
        id=u.id, username=u.username, full_name=u.full_name, role=u.role, rank=u.rank, station_id=u.station_id,
        station_name=u.station.name if u.station else None, district_id=u.district_id,
        district_name=u.district.name if u.district else None, is_active=u.is_active,
        totp_enabled=u.totp_enabled, must_change_password=u.must_change_password,
    )


def _fail(db, request: Request, *, action: str, user: User | None, username: str | None, status: int, msg: str, detail: dict):
    audit.append(db, action=action, user=user, actor_username=username, outcome="failure", ip=client_ip(request), detail=detail)
    db.commit()
    raise HTTPException(status, msg)


def _register_failure(db, request: Request, user: User, reason: str):
    """Counts a failed credential attempt, locking the account at the threshold, then raises 401."""
    s = request.app.state.settings
    user.failed_attempts += 1
    locked = user.failed_attempts >= s.lockout_threshold
    if locked:
        user.locked_until = utcnow_plus(s.lockout_minutes)
        user.failed_attempts = 0
    audit.append(db, action="LOGIN_FAILED", user=user, outcome="failure", ip=client_ip(request), detail={"reason": reason})
    if locked:
        audit.append(db, action="ACCOUNT_LOCKED", user=user, outcome="alert", ip=client_ip(request),
                     detail={"minutes": s.lockout_minutes})
    db.commit()
    raise HTTPException(401, GENERIC_FAIL if reason != "bad_totp" else "Invalid authentication code")


def _check_not_locked(db, request: Request, user: User):
    if user.locked_until and user.locked_until > utcnow():
        _fail(db, request, action="LOGIN_BLOCKED", user=user, username=None, status=423,
              msg="Account temporarily locked. Try again later.", detail={"reason": "locked"})


def _rate_limit(request: Request, db, bucket: str) -> None:
    """Per-client-IP throttle (per-account lockout is separate). Only the first refusal in a window is audited."""
    try:
        enforce(request, bucket, request.app.state.settings.login_attempts_per_minute)
    except RateLimited as exc:
        if exc.first:
            audit.append(db, action="RATE_LIMITED", outcome="alert", ip=client_ip(request), detail={"bucket": bucket})
            db.commit()
        raise


def _session_token(request: Request, user: User, session_start: int | None = None) -> StageTokenOut:
    s = request.app.state.settings
    return StageTokenOut(
        stage="authenticated", token=make_token(s, user.id, user.token_version, "access", s.access_token_minutes, session_start),
        must_change_password=user.must_change_password,
    )


@router.post("/login", response_model=StageTokenOut)
def login(body: LoginIn, request: Request, db: DbSession):
    s = request.app.state.settings
    _rate_limit(request, db, "login")
    uname = body.username.strip().lower()
    user = db.execute(select(User).where(User.username == uname)).scalar_one_or_none()
    if user is None:
        verify_password(body.password, DUMMY_HASH)  # equalise timing with the real-user path
        _fail(db, request, action="LOGIN_FAILED", user=None, username=uname[:64], status=401, msg=GENERIC_FAIL,
              detail={"reason": "unknown_user"})
    _check_not_locked(db, request, user)
    if not verify_password(body.password, user.password_hash):
        _register_failure(db, request, user, "bad_password")
    if not user.is_active:
        _fail(db, request, action="LOGIN_FAILED", user=user, username=None, status=401, msg=GENERIC_FAIL,
              detail={"reason": "inactive"})

    stage = "mfa" if user.totp_enabled else "mfa_setup"
    token = make_token(s, user.id, user.token_version, stage, s.mfa_token_minutes)
    audit.append(db, action="LOGIN_PASSWORD_OK", user=user, ip=client_ip(request), detail={"next": stage})
    db.commit()
    return StageTokenOut(stage="mfa_required" if user.totp_enabled else "mfa_setup_required", token=token)


@router.post("/mfa/verify", response_model=StageTokenOut)
def mfa_verify(body: CodeIn, request: Request, db: DbSession, user: User = Depends(stage_user("mfa"))):
    _rate_limit(request, db, "mfa")
    _check_not_locked(db, request, user)
    secret = decrypt_field(request.app.state.kek, user.totp_secret_enc)
    step = verify_totp(secret, body.code, user.totp_last_step)
    if step is None:
        _register_failure(db, request, user, "bad_totp")
    user.totp_last_step, user.failed_attempts, user.locked_until = step, 0, None
    audit.append(db, action="LOGIN_SUCCESS", user=user, ip=client_ip(request))
    db.commit()
    return _session_token(request, user)


@router.post("/mfa/setup", response_model=MfaSetupOut)
def mfa_setup(request: Request, db: DbSession, user: User = Depends(stage_user("mfa_setup"))):
    if user.totp_enabled:
        raise HTTPException(409, "MFA is already enrolled; ask your station admin to reset it")
    secret = new_totp_secret()
    user.totp_secret_enc = encrypt_field(request.app.state.kek, secret)
    db.commit()
    return MfaSetupOut(secret=secret, otpauth_uri=totp_uri(secret, user.username, request.app.state.settings.totp_issuer))


@router.post("/mfa/enable", response_model=StageTokenOut)
def mfa_enable(body: CodeIn, request: Request, db: DbSession, user: User = Depends(stage_user("mfa_setup"))):
    _rate_limit(request, db, "mfa")
    _check_not_locked(db, request, user)
    if user.totp_enabled or not user.totp_secret_enc:
        raise HTTPException(409, "Call /mfa/setup first (or MFA is already enrolled)")
    step = verify_totp(decrypt_field(request.app.state.kek, user.totp_secret_enc), body.code, 0)
    if step is None:
        _register_failure(db, request, user, "bad_totp")
    user.totp_enabled, user.totp_last_step, user.failed_attempts, user.locked_until = True, step, 0, None
    audit.append(db, action="MFA_ENROLLED", user=user, ip=client_ip(request))
    audit.append(db, action="LOGIN_SUCCESS", user=user, ip=client_ip(request))
    db.commit()
    return _session_token(request, user)


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(access_user_pw)):
    return user_out(user)


@router.post("/change-password", response_model=StageTokenOut)
def change_password(body: ChangePasswordIn, request: Request, db: DbSession, user: User = Depends(access_user_pw)):
    if not verify_password(body.current_password, user.password_hash):
        _fail(db, request, action="PASSWORD_CHANGE_FAILED", user=user, username=None, status=400,
              msg="Current password is incorrect", detail={})
    problem = password_problem(body.new_password, user.username)
    if problem:
        raise HTTPException(400, problem)
    if body.new_password == body.current_password:
        raise HTTPException(400, "New password must differ from the current one")
    user.password_hash = hash_password(body.new_password)
    user.must_change_password = False
    user.token_version += 1  # signs out every other session
    audit.append(db, action="PASSWORD_CHANGED", user=user, ip=client_ip(request))
    db.commit()
    return _session_token(request, user)


@router.post("/refresh", response_model=StageTokenOut)
def refresh(request: Request, user: User = Depends(access_user)):
    """Swaps a still-valid session token for a fresh one (a sliding window while the user is working). The session's
    original start time is carried over, so it can never be extended past `session_max_hours` in total."""
    s = request.app.state.settings
    started = int(request.state.claims.get("sat", 0))
    if time.time() - started > s.session_max_hours * 3600:
        raise HTTPException(401, "This session has reached its maximum length. Please sign in again.")
    return _session_token(request, user, session_start=started)


@router.post("/logout", status_code=204)
def logout(request: Request, db: DbSession, user: User = Depends(access_user_pw)):
    user.token_version += 1
    audit.append(db, action="LOGOUT", user=user, ip=client_ip(request))
    db.commit()
