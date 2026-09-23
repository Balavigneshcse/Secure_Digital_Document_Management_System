from __future__ import annotations

from typing import Annotated, Iterator

import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from . import audit
from .models import User
from .security import decode_token

_bearer = HTTPBearer(auto_error=False)


def get_db(request: Request) -> Iterator[Session]:
    with request.app.state.session_factory() as db:
        yield db


def client_ip(request: Request) -> str | None:
    from .netutil import resolve_ip

    return resolve_ip(request)


def _unauthorized(msg: str = "Not authenticated") -> HTTPException:
    return HTTPException(401, msg, headers={"WWW-Authenticate": "Bearer"})


def stage_user(*stages: str, allow_pw_change: bool = False):
    """Dependency factory: authenticates a bearer token issued for one of the given login stages."""

    def dep(
        request: Request,
        creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
        db: Session = Depends(get_db),
    ) -> User:
        if creds is None:
            raise _unauthorized()
        try:
            payload = decode_token(request.app.state.settings, creds.credentials)
        except jwt.PyJWTError:
            raise _unauthorized("Invalid or expired token")
        if payload["stage"] not in stages:
            raise _unauthorized("Wrong token type for this endpoint")
        user = db.get(User, int(payload["sub"]))
        if user is None or not user.is_active or payload.get("tv") != user.token_version:
            raise _unauthorized("Session is no longer valid")
        if payload["stage"] == "access" and user.must_change_password and not allow_pw_change:
            raise HTTPException(403, "password_change_required")
        request.state.claims = payload
        return user

    return dep


access_user = stage_user("access")
access_user_pw = stage_user("access", allow_pw_change=True)
CurrentUser = Annotated[User, Depends(access_user)]
DbSession = Annotated[Session, Depends(get_db)]


def require_role(*roles: str):
    def dep(request: Request, user: User = Depends(access_user), db: Session = Depends(get_db)) -> User:
        if user.role not in roles:
            db.rollback()
            audit.append(
                db, action="ACCESS_DENIED", user=user, outcome="denied", ip=client_ip(request),
                detail={"endpoint": f"{request.method} {request.url.path}", "reason": "role"},
            )
            db.commit()
            raise HTTPException(403, "Your role does not permit this action")
        return user

    return dep
