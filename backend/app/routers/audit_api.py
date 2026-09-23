from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from sqlalchemy import func, select

from .. import audit
from ..deps import DbSession, client_ip, require_role
from ..models import AuditLog, User

router = APIRouter(prefix="/api/audit", tags=["audit"])
Auditor = Depends(require_role("auditor"))
DATE = r"^\d{4}-\d{2}-\d{2}$"


def _filtered(actor, action, case_number, outcome, date_from, date_to):
    q = select(AuditLog)
    if actor:
        q = q.where(AuditLog.actor_username == actor.lower())
    if action:
        q = q.where(AuditLog.action == action)
    if case_number:
        q = q.where(AuditLog.case_number == case_number)
    if outcome:
        q = q.where(AuditLog.outcome == outcome)
    if date_from:
        q = q.where(AuditLog.ts >= date_from)
    if date_to:
        q = q.where(AuditLog.ts <= date_to + "T23:59:59.999999Z")
    return q


@router.get("")
def list_entries(
    db: DbSession,
    actor: str | None = Query(None, max_length=64),
    action: str | None = Query(None, max_length=48),
    case_number: str | None = Query(None, max_length=48),
    outcome: str | None = Query(None, max_length=16),
    date_from: str | None = Query(None, pattern=DATE),
    date_to: str | None = Query(None, pattern=DATE),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _: User = Auditor,
):
    q = _filtered(actor, action, case_number, outcome, date_from, date_to)
    total = db.scalar(select(func.count()).select_from(q.subquery()))
    rows = db.execute(q.order_by(AuditLog.id.desc()).limit(limit).offset(offset)).scalars().all()
    return {"total": total, "items": [audit.to_dict(e) for e in rows]}


@router.get("/verify")
def verify(request: Request, db: DbSession, user: User = Auditor):
    result = audit.verify_chain(db, request.app.state.ledger, request.app.state.chain_id)
    audit.append(db, action="AUDIT_VERIFIED", user=user, outcome="success" if result["ok"] else "alert",
                 ip=client_ip(request), detail={"ok": result["ok"], "checked": result["checked"]})
    db.commit()
    return result


@router.post("/anchor")
def anchor(request: Request, db: DbSession, user: User = Auditor):
    result = audit.anchor_head(db, request.app.state.ledger, request.app.state.chain_id)
    audit.append(db, action="AUDIT_ANCHORED", user=user, ip=client_ip(request), detail=result or {"skipped": "already anchored"})
    db.commit()
    return result or {"skipped": "audit head is already anchored"}


@router.get("/export")
def export(
    request: Request,
    db: DbSession,
    actor: str | None = Query(None, max_length=64),
    action: str | None = Query(None, max_length=48),
    case_number: str | None = Query(None, max_length=48),
    outcome: str | None = Query(None, max_length=16),
    date_from: str | None = Query(None, pattern=DATE),
    date_to: str | None = Query(None, pattern=DATE),
    user: User = Auditor,
):
    rows = db.execute(_filtered(actor, action, case_number, outcome, date_from, date_to).order_by(AuditLog.id.asc()).limit(50_000)).scalars().all()
    audit.append(db, action="AUDIT_EXPORTED", user=user, ip=client_ip(request), detail={"rows": len(rows)})
    db.commit()
    return Response(
        content=audit.to_csv(rows), media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="sdms-audit-export.csv"'},
    )
