"""Home dashboard and in-app alerts.

Alerts are not a second log: they are the audit log's own alert entries (tampering detected, malware rejected,
accounts locked), filtered to what each user is responsible for, with a per-user "read up to here" marker."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Query
from sqlalchemy import String, cast, func, select

from ..db import utcnow, utcnow_plus
from ..deps import DbSession, access_user
from ..models import AlertRead, AuditLog, Case, CaseShare, Document, User
from ..permissions import content_scope, document_scope
from .evidence import ACTION_LABELS, approval_queue

router = APIRouter(prefix="/api", tags=["dashboard"])
CASE_ALERTS = ("TAMPER_DETECTED", "UPLOAD_REJECTED_MALWARE")
ACCOUNT_ALERTS = ("ACCOUNT_LOCKED", "RATE_LIMITED")
ALERT_LABELS = {**ACTION_LABELS, "ACCOUNT_LOCKED": "Account locked after failed sign-ins", "RATE_LIMITED": "Too many requests from one address"}


def _case_scope(user: User):
    """Cases this user is responsible for, as a SQL condition on `Case` (None = no cases at all)."""
    if user.role == "admin":
        return Case.station_id == user.station_id if user.station_id else None
    if user.role == "auditor":
        return None
    return content_scope(user)


def _alert_filter(user: User):
    if user.role == "auditor":
        return AuditLog.outcome == "alert"
    if user.role == "admin" and user.rank == "system":
        return AuditLog.action.in_(ACCOUNT_ALERTS)
    if user.role in ("forensic", "defence"):  # only about documents they filed themselves
        own = select(cast(Document.id, String)).where(Document.created_by == user.id)
        return (AuditLog.action == "TAMPER_DETECTED") & (AuditLog.resource_type == "document") & AuditLog.resource_id.in_(own)
    scope = _case_scope(user)
    if scope is None:
        return None
    return AuditLog.action.in_(CASE_ALERTS) & AuditLog.case_number.in_(select(Case.case_number).where(scope))


def _alerts(db, user: User, limit: int) -> tuple[list[dict], int]:
    cond = _alert_filter(user)
    if cond is None:
        return [], 0
    seen = db.get(AlertRead, user.id)
    last = seen.last_seen_audit_id if seen else 0
    unread = db.scalar(select(func.count(AuditLog.id)).where(cond, AuditLog.id > last)) or 0
    rows = db.execute(select(AuditLog).where(cond).order_by(AuditLog.id.desc()).limit(limit)).scalars().all()
    case_ids = dict(db.execute(select(Case.case_number, Case.id).where(Case.case_number.in_({r.case_number for r in rows if r.case_number}))).all()) if rows else {}
    out = []
    for e in rows:
        d = json.loads(e.detail or "{}")
        out.append({
            "id": e.id, "ts": e.ts, "action": e.action, "label": ALERT_LABELS.get(e.action, e.action), "unread": e.id > last,
            "actor": e.actor_username, "case_number": e.case_number, "case_id": case_ids.get(e.case_number),
            "document_id": int(e.resource_id) if e.resource_type == "document" and e.resource_id else None,
            "reasons": d.get("reasons") or ([d["signature"]] if d.get("signature") else []),
        })
    return out, unread


@router.get("/alerts")
def alerts(db: DbSession, user: User = Depends(access_user), limit: int = Query(50, ge=1, le=200)):
    items, unread = _alerts(db, user, limit)
    return {"unread": unread, "items": items}


@router.post("/alerts/seen", status_code=204)
def alerts_seen(db: DbSession, user: User = Depends(access_user)):
    cond = _alert_filter(user)
    newest = db.scalar(select(func.max(AuditLog.id)).where(cond)) if cond is not None else None
    if newest:
        row = db.get(AlertRead, user.id) or AlertRead(user_id=user.id, last_seen_audit_id=0)
        row.last_seen_audit_id = max(row.last_seen_audit_id, newest)
        db.add(row)
        db.commit()


@router.get("/dashboard")
def dashboard(db: DbSession, user: User = Depends(access_user)):
    """Role-aware summary for the home page."""
    scope = _case_scope(user)
    out: dict = {"cases": None, "documents": None, "approvals": approval_queue(db, user), "returned": [], "expiring_shares": []}
    if scope is not None:
        rows = db.execute(select(Case.status, Case.stage, func.count(Case.id)).where(scope).group_by(Case.status, Case.stage)).all()
        by_stage: dict[str, int] = {}
        for status, stage, n in rows:
            by_stage[stage] = by_stage.get(stage, 0) + n
        out["cases"] = {"open": sum(n for s, _, n in rows if s == "open"), "closed": sum(n for s, _, n in rows if s != "open"),
                        "by_stage": by_stage}
        out["recent_cases"] = [
            {"id": c.id, "case_number": c.case_number, "title": c.title, "status": c.status, "stage": c.stage}
            for c in db.execute(select(Case).where(scope).order_by(Case.id.desc()).limit(6)).scalars()
        ]
        if user.role != "admin":
            out["documents"] = db.scalar(select(func.count(Document.id)).join(Case, Case.id == Document.case_id)
                                         .where(scope, document_scope(user))) or 0
        if user.role in ("officer", "admin"):
            soon = utcnow_plus(7 * 24 * 60)
            q = (select(CaseShare, Case).join(Case, Case.id == CaseShare.case_id)
                 .where(scope, CaseShare.expires_at.is_not(None), CaseShare.expires_at > utcnow(), CaseShare.expires_at <= soon))
            out["expiring_shares"] = [
                {"case_id": c.id, "case_number": c.case_number, "username": s.shared_with.username, "role": s.shared_with.role,
                 "expires_at": s.expires_at}
                for s, c in db.execute(q.order_by(CaseShare.expires_at)).all()
            ]
    if user.role == "officer":
        out["returned"] = [
            {"document_id": d.id, "title": d.title, "case_id": d.case_id, "note": d.approval_note,
             "by": d.approver.username if d.approver else None, "at": d.approved_at}
            for d in db.execute(select(Document).where(Document.created_by == user.id, Document.approval_status == "returned")
                                .order_by(Document.id.desc())).scalars()
        ]
    items, unread = _alerts(db, user, 8)
    out["alerts"], out["alerts_unread"] = items, unread
    return out
