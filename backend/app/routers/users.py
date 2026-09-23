from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from .. import audit
from ..deps import DbSession, client_ip, require_role
from ..models import Station, User
from ..routers.auth import user_out
from ..schemas import UserCreate, UserOut, UserPatch
from ..security import hash_password, password_problem

router = APIRouter(prefix="/api/users", tags=["users"])
AdminUser = Depends(require_role("admin"))
Sharer = Depends(require_role("officer", "admin"))  # needs to know who they can share a case with


def _officer_in_station(db, admin: User, user_id: int) -> User:
    target = db.get(User, user_id)
    if target is None or target.role != "officer" or target.station_id != admin.station_id:
        raise HTTPException(404, "Not found")
    return target


@router.get("", response_model=list[UserOut])
def list_users(db: DbSession, admin: User = AdminUser):
    rows = db.execute(
        select(User).where(User.station_id == admin.station_id, User.role == "officer").order_by(User.username)
    ).scalars()
    return [user_out(u) for u in rows]


@router.get("/reviewers", response_model=list[UserOut])
def list_reviewers(db: DbSession, user: User = Sharer):
    """Active forensic/judge accounts, for the "share this case with" picker. Judges aren't district-restricted
    (any judge can be manually granted a share); a forensic lab outside the requester's own district is left
    out, since a share with it would be rejected anyway - see the same-district check in `share()`."""
    my_district = db.execute(select(Station.district_id).where(Station.id == user.station_id)).scalar_one_or_none() \
        if user.station_id else None
    q = select(User).where(User.role.in_(("forensic", "judge")), User.is_active)
    if my_district is not None:
        q = q.where((User.role == "judge") | (User.district_id == my_district))
    rows = db.execute(q.order_by(User.role, User.username)).scalars()
    return [user_out(u) for u in rows]


@router.post("", response_model=UserOut, status_code=201)
def create_user(body: UserCreate, request: Request, db: DbSession, admin: User = AdminUser):
    if admin.station_id is None:
        raise HTTPException(400, "Admin account has no station")
    problem = password_problem(body.password, body.username)
    if problem:
        raise HTTPException(400, problem)
    user = User(
        username=body.username.lower(), full_name=body.full_name, password_hash=hash_password(body.password),
        role="officer", station_id=admin.station_id, must_change_password=True,
    )
    db.add(user)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Username already exists")
    audit.append(db, action="USER_CREATED", user=admin, resource_type="user", resource_id=user.id,
                 ip=client_ip(request), detail={"username": user.username, "role": user.role})
    db.commit()
    return user_out(user)


@router.patch("/{user_id}", response_model=UserOut)
def set_active(user_id: int, body: UserPatch, request: Request, db: DbSession, admin: User = AdminUser):
    target = _officer_in_station(db, admin, user_id)
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
    target = _officer_in_station(db, admin, user_id)
    target.totp_enabled, target.totp_secret_enc, target.totp_last_step = False, None, 0
    target.token_version += 1
    audit.append(db, action="MFA_RESET", user=admin, resource_type="user", resource_id=target.id,
                 ip=client_ip(request), detail={"username": target.username})
    db.commit()
    return user_out(target)


@router.post("/{user_id}/unlock", response_model=UserOut)
def unlock(user_id: int, request: Request, db: DbSession, admin: User = AdminUser):
    target = _officer_in_station(db, admin, user_id)
    target.failed_attempts, target.locked_until = 0, None
    audit.append(db, action="ACCOUNT_UNLOCKED", user=admin, resource_type="user", resource_id=target.id,
                 ip=client_ip(request), detail={"username": target.username})
    db.commit()
    return user_out(target)
