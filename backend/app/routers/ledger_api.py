from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from .. import audit
from ..deps import DbSession, client_ip, require_role
from ..models import User

router = APIRouter(prefix="/api/ledger", tags=["ledger"])
Auditor = Depends(require_role("auditor"))


@router.get("/status")
def status(request: Request, _: User = Auditor):
    return request.app.state.ledger.status()


@router.get("/blocks")
def blocks(
    request: Request,
    kind: str | None = Query(None, max_length=32),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _: User = Auditor,
):
    items, total = request.app.state.ledger.blocks(offset=offset, limit=limit, kind=kind)
    return {"total": total, "items": [b.as_dict() for b in items]}


@router.get("/verify")
def verify(request: Request, db: DbSession, user: User = Auditor):
    result = request.app.state.ledger.verify_chain()
    audit.append(db, action="LEDGER_VERIFIED", user=user, outcome="success" if result["ok"] else "alert",
                 ip=client_ip(request), detail={"ok": result["ok"], "checked": result["checked"]})
    db.commit()
    return result


@router.get("/tx/{tx_id}")
def tx(tx_id: str, request: Request, _: User = Auditor):
    block = request.app.state.ledger.get_by_tx(tx_id)
    if block is None:
        raise HTTPException(404, "Not found")
    return block.as_dict()
