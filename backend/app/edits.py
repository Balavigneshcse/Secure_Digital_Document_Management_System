"""Edit history: what changed in a case or document, when, by whom and why.

Two stores, on purpose. The hash-chained audit log records *that* an edit happened (time, editor, which fields) plus
the SHA-256 of the full edit record; the old and new values themselves sit in `edit_history`, readable only by
people who may see the case (auditors may not read case data). The history shown to officers and judges is built
from the audit entries, so a deleted `edit_history` row shows up as a missing record and an altered one fails its
hash - an edit cannot be quietly hidden or rewritten.
"""
from __future__ import annotations

import difflib
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import audit
from .db import utcnow
from .ledger import canonical, sha256_hex
from .models import AuditLog, Case, Document, EditRecord, User

EDIT_ACTIONS = {
    "CASE_EDITED": "case", "DOCUMENT_EDITED": "document", "DOCUMENT_VERSION_ADDED": "version",
    "DOCUMENT_APPROVED": "approval", "DOCUMENT_RETURNED": "approval",
}
MAX_HISTORY = 300
MAX_DIFF_LINES = 600
MAX_DIFF_LINE_CHARS = 600


def change(field: str, old, new) -> dict:
    return {"field": field, "old": None if old is None else str(old), "new": None if new is None else str(new)}


def _hash(rec: EditRecord) -> str:
    return sha256_hex(canonical({
        "case_id": rec.case_id, "document_id": rec.document_id, "kind": rec.kind, "edited_by": rec.edited_by,
        "edited_at": rec.edited_at, "reason": rec.reason, "changes": rec.changes,
    }))


def record(
    db: Session, *, action: str, user: User, case: Case, document: Document | None, reason: str, changes: list[dict],
    ip: str | None, detail: dict | None = None,
) -> EditRecord:
    """Writes the edit record and its audit entry into the caller's transaction (commit is the caller's job)."""
    rec = EditRecord(
        case_id=case.id, document_id=document.id if document else None, kind=EDIT_ACTIONS[action], edited_by=user.id,
        edited_at=utcnow(), reason=reason.strip(), changes=canonical(changes), record_hash="",
    )
    rec.record_hash = _hash(rec)
    db.add(rec)
    db.flush()
    entry = audit.append(
        db, action=action, user=user, resource_type="document" if document else "case",
        resource_id=document.id if document else case.id, case_number=case.case_number, ip=ip,
        # field names only - never the values: auditors read this log and must not see case data
        detail={**(detail or {}), "fields": [c["field"] for c in changes], "record_hash": rec.record_hash},
    )
    rec.audit_id = entry.id
    db.flush()
    return rec


def _entry_problem(db: Session, e: AuditLog) -> str | None:
    """Checks this one audit entry against its neighbours (the auditor's full-chain check covers the rest)."""
    if audit._entry_hash(e.prev_hash, e) != e.entry_hash:
        return "The audit entry for this edit was altered"
    nxt = db.execute(select(AuditLog.prev_hash).where(AuditLog.id > e.id).order_by(AuditLog.id.asc()).limit(1)).scalar_one_or_none()
    if nxt is not None and nxt != e.entry_hash:
        return "The audit chain is broken at this edit"
    return None


def history(db: Session, case: Case, *, document_ids: set[int] | None, include_case: bool = True) -> list[dict]:
    """Edits to `case` (if `include_case`) and to its documents, newest first. `document_ids` limits document
    entries to those the viewer may read (None = all of the case's documents)."""
    entries = db.execute(
        select(AuditLog)
        .where(AuditLog.case_number == case.case_number, AuditLog.action.in_(EDIT_ACTIONS), AuditLog.outcome == "success")
        .order_by(AuditLog.id.desc()).limit(MAX_HISTORY)
    ).scalars().all()
    details = {e.id: json.loads(e.detail or "{}") for e in entries}
    entries = [e for e in entries if details[e.id].get("record_hash")]  # versions filed before edit records existed
    records = {
        r.audit_id: r
        for r in db.execute(select(EditRecord).where(EditRecord.audit_id.in_([e.id for e in entries]))).scalars()
    } if entries else {}
    titles = dict(db.execute(select(Document.id, Document.title).where(Document.case_id == case.id)).all())
    names = dict(db.execute(select(User.username, User.full_name).where(User.username.in_({e.actor_username for e in entries}))).all()) if entries else {}

    out = []
    for e in entries:
        kind = EDIT_ACTIONS[e.action]
        doc_id = int(e.resource_id) if kind != "case" and e.resource_id else None
        if kind == "case":
            if not include_case:
                continue
        elif document_ids is not None and doc_id not in document_ids:
            continue
        d, rec = details[e.id], records.get(e.id)
        problem = _entry_problem(db, e)
        if rec is None:
            problem = problem or "The record of what was changed is missing from the database"
        elif _hash(rec) != rec.record_hash or rec.record_hash != d.get("record_hash"):
            problem = problem or "The record of what was changed was altered after it was written"
        out.append({
            "id": e.id, "ts": e.ts, "kind": kind, "editor": e.actor_username, "editor_name": names.get(e.actor_username),
            "editor_role": e.actor_role, "document_id": doc_id, "document_title": titles.get(doc_id) if doc_id else None,
            "version_no": d.get("version_no"), "reason": rec.reason if rec else None,
            "changes": json.loads(rec.changes) if rec else [change(f, None, None) for f in d.get("fields", [])],
            "verified": problem is None, "problem": problem,
        })
    return out


def text_diff(old: str, new: str) -> dict:
    """Line diff of two versions' extracted text, for display."""
    a, b = old.splitlines(), new.splitlines()
    lines, added, removed = [], 0, 0
    for ln in difflib.unified_diff(a, b, lineterm="", n=2):
        if ln.startswith(("---", "+++")):
            continue
        op = ln[0] if ln and ln[0] in "+-@" else " "
        added += op == "+"
        removed += op == "-"
        lines.append({"op": op, "text": (ln if op == "@" else ln[1:])[:MAX_DIFF_LINE_CHARS]})
    return {"added": added, "removed": removed, "truncated": len(lines) > MAX_DIFF_LINES, "lines": lines[:MAX_DIFF_LINES]}
