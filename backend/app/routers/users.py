"""User administration.

Two kinds of admin:
  * a station admin (role=admin, rank=officer) manages the plain officer accounts of their own station;
  * a system administrator (role=admin, rank=system, no station) manages accounts of every role - forensic labs,
    judges, prosecutors, defence lawyers, auditors, station admins - which otherwise need the operator CLI.
Neither can open a case document. Forgotten passwords are reset here (a one-time temporary password the user must
change at next sign-in); nobody, admins included, ever sees a user's real password.
"""
from __future__ import annotations

import secrets
import string

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from .. import audit
from ..deps import DbSession, client_ip, require_role
from ..models import ROLES, District, Station, User
from ..permissions import SHARE_ROLES
from ..routers.auth import user_out
from ..schemas import UserCreate, UserOut, UserPatch
from ..security import hash_password, password_problem

router = APIRouter(prefix="/api/users", tags=["users"])
AdminUser = Depends(require_role("admin"))
Sharer = Depends(require_role("officer", "admin"))  # needs to know who they can share a case with

VALID_RANKS = {
    "officer": ("officer", "station_head", "superintendent"),
    "judge": ("officer", "district_court", "high_court"),
    "admin": ("officer", "system"),
}


def is_system_admin(u: User) -> bool:
    return u.role == "admin" and u.rank == "system"


def _manageable(db, admin: User, user_id: int) -> User:
    """The account this admin may manage, else 404 (a station admin: officers of their station only)."""
    target = db.get(User, user_id)
    if target is None or target.id == admin.id:
        raise HTTPException(404, "Not found")
    if is_system_admin(admin):
        return target
    if target.role != "officer" or target.station_id != admin.station_id:
        raise HTTPException(404, "Not found")
    return target


def _check_rank(admin: User, target_role: str, rank: str) -> None:
    allowed = VALID_RANKS.get(target_role, ("officer",))
    if not is_system_admin(admin):
        allowed = ("officer", "station_head")  # a station admin promotes within the station only
    if rank not in allowed:
        raise HTTPException(422, f"rank must be one of {', '.join(allowed)} for this account")


@router.get("", response_model=list[UserOut])
def list_users(db: DbSession, admin: User = AdminUser):
    q = select(User)
    if not is_system_admin(admin):
        q = q.where(User.station_id == admin.station_id, User.role == "officer")
    return [user_out(u) for u in db.execute(q.order_by(User.role, User.username)).scalars()]


@router.get("/org")
def organisation(db: DbSession, admin: User = AdminUser):
    """Districts and stations, for the account form."""
    return {
        "districts": [{"id": d.id, "code": d.code, "name": d.name} for d in db.execute(select(District).order_by(District.name)).scalars()],
        "stations": [{"id": s.id, "code": s.code, "name": s.name, "district_id": s.district_id}
                     for s in db.execute(select(Station).order_by(Station.name)).scalars()],
    }


@router.get("/reviewers", response_model=list[UserOut])
def list_reviewers(db: DbSession, user: User = Sharer):
    """Active forensic/judge/prosecutor/defence accounts, for the "share this case with" picker. Only forensic labs
    are district-restricted: one outside the requester's own district is left out, since a share with it would be
    rejected anyway - see the same-district check in `share()`."""
    my_district = db.execute(select(Station.district_id).where(Station.id == user.station_id)).scalar_one_or_none() \
        if user.station_id else None
    q = select(User).where(User.role.in_(SHARE_ROLES), User.is_active)
    if my_district is not None:
        q = q.where((User.role != "forensic") | (User.district_id == my_district))
    rows = db.execute(q.order_by(User.role, User.username)).scalars()
    return [user_out(u) for u in rows]


@router.post("", response_model=UserOut, status_code=201)
def create_user(body: UserCreate, request: Request, db: DbSession, admin: User = AdminUser):
    problem = password_problem(body.password, body.username)
    if problem:
        raise HTTPException(400, problem)
    station_id, district_id = body.station_id, body.district_id
    if not is_system_admin(admin):
        if body.role != "officer" or body.rank != "officer":
            raise HTTPException(403, "Only a system administrator can create this kind of account")
        if admin.station_id is None:
            raise HTTPException(400, "Admin account has no station")
        station_id, district_id = admin.station_id, None
    else:
        if body.role not in ROLES:
            raise HTTPException(422, f"role must be one of {', '.join(ROLES)}")
        _check_rank(admin, body.role, body.rank)
        needs_station = (body.role == "officer" and body.rank != "superintendent") or (body.role == "admin" and body.rank != "system")
        if needs_station and station_id is None:
            raise HTTPException(422, "A station is required for this account")
        if (body.role == "forensic" or (body.role == "judge" and body.rank == "district_court")) and district_id is None:
            raise HTTPException(422, "A district is required for a forensic lab or a district court judge")
        if station_id is not None and db.get(Station, station_id) is None:
            raise HTTPException(422, "No such station")
        if district_id is not None and db.get(District, district_id) is None:
            raise HTTPException(422, "No such district")
        if body.role == "admin" and body.rank == "system":
            station_id = None
    user = User(
        username=body.username.lower(), full_name=body.full_name, password_hash=hash_password(body.password),
        role=body.role, rank=body.rank, station_id=station_id, district_id=district_id, must_change_password=True,
    )
    db.add(user)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Username already exists")
    audit.append(db, action="USER_CREATED", user=admin, resource_type="user", resource_id=user.id,
                 ip=client_ip(request), detail={"username": user.username, "role": user.role, "rank": user.rank})
    db.commit()
    db.refresh(user)
    return user_out(user)


@router.patch("/{user_id}", response_model=UserOut)
def set_active(user_id: int, body: UserPatch, request: Request, db: DbSession, admin: User = AdminUser):
    target = _manageable(db, admin, user_id)
    if target.rank != body.rank:
        _check_rank(admin, target.role, body.rank)
    if target.is_active != body.is_active:
        target.is_active = body.is_active
        if not body.is_active:
            target.token_version += 1  # kill live sessions immediately
        audit.append(db, action="USER_ACTIVATED" if body.is_active else "USER_DEACTIVATED", user=admin,
                     resource_type="user", resource_id=target.id, ip=client_ip(request), detail={"username": target.username})
    if target.rank != body.rank:
        old_rank = target.rank
        target.rank = body.rank
        audit.append(db, action="USER_RANK_CHANGED", user=admin, resource_type="user", resource_id=target.id,
                     ip=client_ip(request), detail={"username": target.username, "from": old_rank, "to": body.rank})
    db.commit()
    return user_out(target)


@router.post("/{user_id}/reset-mfa", response_model=UserOut)
def reset_mfa(user_id: int, request: Request, db: DbSession, admin: User = AdminUser):
    target = _manageable(db, admin, user_id)
    target.totp_enabled, target.totp_secret_enc, target.totp_last_step = False, None, 0
    target.token_version += 1
    audit.append(db, action="MFA_RESET", user=admin, resource_type="user", resource_id=target.id,
                 ip=client_ip(request), detail={"username": target.username})
    db.commit()
    return user_out(target)


@router.post("/{user_id}/unlock", response_model=UserOut)
def unlock(user_id: int, request: Request, db: DbSession, admin: User = AdminUser):
    target = _manageable(db, admin, user_id)
    target.failed_attempts, target.locked_until = 0, None
    audit.append(db, action="ACCOUNT_UNLOCKED", user=admin, resource_type="user", resource_id=target.id,
                 ip=client_ip(request), detail={"username": target.username})
    db.commit()
    return user_out(target)


def temporary_password() -> str:
    alphabet = string.ascii_letters + string.digits
    while True:
        pw = "".join(secrets.choice(alphabet) for _ in range(14))
        if any(c.isdigit() for c in pw) and any(c.isalpha() for c in pw):
            return pw


@router.post("/{user_id}/reset-password")
def reset_password(user_id: int, request: Request, db: DbSession, admin: User = AdminUser):
    """Forgotten password: issues a one-time temporary password (shown to the admin once, never stored or logged in
    clear), signs the user out everywhere, clears any lockout, and forces a new password at next sign-in. Their
    authenticator stays enrolled, so the temporary password alone still cannot sign in."""
    target = _manageable(db, admin, user_id)
    temp = temporary_password()
    target.password_hash = hash_password(temp)
    target.must_change_password = True
    target.failed_attempts, target.locked_until = 0, None
    target.token_version += 1
    audit.append(db, action="PASSWORD_RESET", user=admin, resource_type="user", resource_id=target.id,
                 ip=client_ip(request), detail={"username": target.username})
    db.commit()
    return {"username": target.username, "temporary_password": temp}
