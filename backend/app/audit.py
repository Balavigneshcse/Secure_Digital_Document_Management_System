"""Hash-chained audit trail.

Each entry stores the hash of its predecessor, so editing or deleting a middle row breaks every
later link. Truncating the *tail* can't be caught by the chain alone, which is why the current
head is periodically anchored on the ledger and `verify` checks that anchor still matches.
"""
from __future__ import annotations

import csv
import io
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import advisory_xact_lock, utcnow
from .ledger import GENESIS_HASH, Ledger, canonical, sha256_hex
from .models import AuditLog, User

ANCHOR_KIND = "AUDIT_ANCHOR"


def _entry_hash(prev_hash: str, e: AuditLog) -> str:
    body = canonical(
        {
            "ts": e.ts, "actor_id": e.actor_id, "actor_username": e.actor_username, "actor_role": e.actor_role,
            "action": e.action, "outcome": e.outcome, "resource_type": e.resource_type,
            "resource_id": e.resource_id, "case_number": e.case_number, "ip": e.ip, "detail": e.detail,
        }
    )
    return sha256_hex(prev_hash + body)


def append(
    db: Session,
    *,
    action: str,
    user: User | None = None,
    actor_username: str | None = None,
    outcome: str = "success",
    resource_type: str | None = None,
    resource_id: str | int | None = None,
    case_number: str | None = None,
    ip: str | None = None,
    detail: dict | None = None,
) -> AuditLog:
    """Adds an entry to the caller's transaction (commit is the caller's job). A transaction-scoped
    PostgreSQL advisory lock serialises appenders, so two concurrent requests can't fork the chain."""
    advisory_xact_lock(db, "sdms-audit-chain")
    last = db.execute(select(AuditLog).order_by(AuditLog.id.desc()).limit(1)).scalar_one_or_none()
    prev_hash = last.entry_hash if last else GENESIS_HASH
    entry = AuditLog(
        ts=utcnow(),
        actor_id=user.id if user else None,
        actor_username=user.username if user else actor_username,
        actor_role=user.role if user else None,
        action=action,
        outcome=outcome,
        resource_type=resource_type,
        resource_id=str(resource_id) if resource_id is not None else None,
        case_number=case_number,
        ip=ip,
        detail=canonical(detail or {}),
        prev_hash=prev_hash,
        entry_hash="",
    )
    entry.entry_hash = _entry_hash(prev_hash, entry)
    db.add(entry)
    db.flush()
    return entry


def verify_chain(db: Session, ledger: Ledger, chain_id: str) -> dict:
    prev_hash, checked = GENESIS_HASH, 0
    hash_at: dict[int, str] = {}
    for e in db.execute(select(AuditLog).order_by(AuditLog.id.asc())).scalars():
        if e.prev_hash != prev_hash:
            return {"ok": False, "checked": checked, "broken_at": e.id, "reason": "broken hash link (row removed or reordered)"}
        if _entry_hash(prev_hash, e) != e.entry_hash:
            return {"ok": False, "checked": checked, "broken_at": e.id, "reason": "entry content altered"}
        prev_hash = e.entry_hash
        hash_at[e.id] = e.entry_hash
        checked += 1

    anchor = ledger.latest(ANCHOR_KIND, chain_id)
    anchored = None
    if anchor:
        aid, ahash = anchor.payload.get("audit_id"), anchor.payload.get("entry_hash")
        if hash_at.get(aid) != ahash:
            return {
                "ok": False, "checked": checked, "broken_at": aid,
                "reason": "ledger-anchored audit entry is missing or differs (log truncated or rewritten)",
            }
        anchored = {"audit_id": aid, "tx_id": anchor.tx_id, "ts": anchor.ts}
    return {"ok": True, "checked": checked, "broken_at": None, "reason": None, "last_anchor": anchored}


def anchor_head(db: Session, ledger: Ledger, chain_id: str) -> dict | None:
    """Writes the current audit head to the ledger. Returns None if nothing new to anchor."""
    head = db.execute(select(AuditLog).order_by(AuditLog.id.desc()).limit(1)).scalar_one_or_none()
    if head is None:
        return None
    last = ledger.latest(ANCHOR_KIND, chain_id)
    if last and last.payload.get("audit_id") == head.id:
        return None
    block = ledger.anchor(ANCHOR_KIND, {"chain_id": chain_id, "audit_id": head.id, "entry_hash": head.entry_hash})
    return {"audit_id": head.id, "tx_id": block.tx_id, "block": block.index}


_EXPORT_FIELDS = [
    "id", "ts", "actor_username", "actor_role", "action", "outcome", "resource_type", "resource_id",
    "case_number", "ip", "detail", "prev_hash", "entry_hash",
]


def to_dict(e: AuditLog) -> dict:
    d = {f: getattr(e, f) for f in _EXPORT_FIELDS}
    d["detail"] = json.loads(e.detail or "{}")
    return d


def to_csv(entries: list[AuditLog]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(_EXPORT_FIELDS)
    for e in entries:
        # Prefix formula-trigger characters so Excel doesn't evaluate attacker-controlled text.
        w.writerow([_csv_safe(getattr(e, f)) for f in _EXPORT_FIELDS])
    return buf.getvalue()


def _csv_safe(v):
    s = "" if v is None else str(v)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s
