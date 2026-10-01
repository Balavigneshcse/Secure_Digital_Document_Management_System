"""Evidence features on top of a stored document: reading it in the browser, its chain of custody, the Section 63
certificate, digital signatures, and the station head's approval of FIRs and charge sheets."""
from __future__ import annotations

import base64
import hashlib
import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from .. import audit, docstore, edits, signing
from ..db import utcnow
from ..deps import DbSession, client_ip, require_role
from ..doc_service import document_out, verify_version
from ..ledger import canonical, sha256_hex
from ..models import AuditLog, Case, Document, Signature, StationOversight, User
from ..permissions import SHARE_ROLES, can_approve, can_sign_document, load_document
from ..schemas import DocumentOut
from ..security import verify_password
from .auth import _check_not_locked, _rate_limit, _register_failure
from .documents import _get_version, _tamper_alert

router = APIRouter(tags=["evidence"])
Reader = Depends(require_role("officer", *SHARE_ROLES))
CustodyReader = Depends(require_role("officer", "judge", "prosecutor"))  # the parties who rely on the evidence

ACTION_LABELS = {
    "DOCUMENT_UPLOADED": "Filed", "DOCUMENT_VERSION_ADDED": "Filed a new version", "DOCUMENT_VIEWED": "Opened the record",
    "DOCUMENT_OPENED": "Viewed the file", "DOCUMENT_DOWNLOADED": "Downloaded the file", "DOCUMENT_VERIFIED": "Verified integrity",
    "TAMPER_DETECTED": "TAMPERING DETECTED", "DOCUMENT_EDITED": "Edited the details", "DOCUMENT_DIFF_VIEWED": "Compared versions",
    "DOCUMENT_SUMMARISED": "Asked the AI for a summary", "CLASSIFICATION_CORRECTED": "Corrected the document type",
    "VERDICT_RECORDED": "Recorded the verdict", "ACCESS_DENIED": "Access refused", "DOCUMENT_APPROVED": "Approved",
    "DOCUMENT_RETURNED": "Returned for correction", "DOCUMENT_SIGNED": "Signed", "SIGN_FAILED": "Signing refused (wrong password)",
    "CERTIFICATE_ISSUED": "Issued a Section 63 certificate", "UPLOAD_REJECTED_MALWARE": "Upload rejected: malware",
}


def _verified(request: Request, db, user: User, doc: Document, v) -> dict:
    report, _ = verify_version(request.app.state, doc, v)
    if report["status"] == "tampered":
        _tamper_alert(db, request, user, doc, report)
        raise HTTPException(409, {"message": "Integrity check failed - possible tampering", "report": report})
    return report


# ---- reading in the browser -------------------------------------------------------------------------------
@router.get("/api/documents/{document_id}/versions/{version_no}/text")
def version_text(document_id: int, version_no: int, request: Request, db: DbSession, user: User = Reader):
    """The text extracted from a version (OCR for scans), for formats a browser can't display (DOCX, TIFF)."""
    doc = load_document(db, request, user, document_id)
    v = _get_version(doc, version_no)
    _verified(request, db, user, doc, v)
    content = docstore.load_contents(request.app.state.mongo, request.app.state.kek, [docstore.meta_key(doc.id, v.version_no)])
    c = next(iter(content.values()), {}) or {}
    audit.append(db, action="DOCUMENT_OPENED", user=user, resource_type="document", resource_id=doc.id,
                 case_number=doc.case.case_number, ip=client_ip(request), detail={"version_no": v.version_no, "as": "text"})
    db.commit()
    text = c.get("ocr_text") or ""
    return {"available": bool(text.strip()), "text": text, "method": c.get("ocr_method"), "language": c.get("language")}


# ---- chain of custody -------------------------------------------------------------------------------------
def custody_entries(db, doc: Document, limit: int = 500) -> list[dict]:
    rows = db.execute(
        select(AuditLog).where(AuditLog.resource_type == "document", AuditLog.resource_id == str(doc.id),
                               AuditLog.action != "CUSTODY_VIEWED").order_by(AuditLog.id.asc()).limit(limit)
    ).scalars().all()
    out = []
    for e in rows:
        d = json.loads(e.detail or "{}")
        out.append({"id": e.id, "ts": e.ts, "actor": e.actor_username, "actor_role": e.actor_role, "action": e.action,
                    "label": ACTION_LABELS.get(e.action, e.action.replace("_", " ").capitalize()), "outcome": e.outcome,
                    "version_no": d.get("version_no")})
    return out


@router.get("/api/documents/{document_id}/custody")
def custody(document_id: int, request: Request, db: DbSession, user: User = CustodyReader):
    """Who did what with this document, and when - every filing, view, download, verification, edit, signature and
    refused attempt, in order, straight from the hash-chained audit log."""
    doc = load_document(db, request, user, document_id)
    out = custody_entries(db, doc)
    audit.append(db, action="CUSTODY_VIEWED", user=user, resource_type="document", resource_id=doc.id,
                 case_number=doc.case.case_number, ip=client_ip(request))
    db.commit()
    return out


# ---- digital signatures -----------------------------------------------------------------------------------
class SignIn(BaseModel):
    password: str = Field(min_length=1, max_length=256)


def _signature_out(request: Request, db, doc: Document, v, s: Signature) -> dict:
    problems = signing.check(request.app.state, db, doc, v, s)
    return {"signer": s.signer.username, "signer_name": s.signer.full_name, "signer_role": s.signer.role,
            "signer_rank": s.signer.rank, "signed_at": s.signed_at, "valid": not problems, "problems": problems,
            "fingerprint": hashlib.sha256(base64.b64decode(s.public_key)).hexdigest()[:16]}


@router.get("/api/documents/{document_id}/versions/{version_no}/signatures")
def list_signatures(document_id: int, version_no: int, request: Request, db: DbSession, user: User = Reader):
    doc = load_document(db, request, user, document_id)
    v = _get_version(doc, version_no)
    sigs = db.execute(select(Signature).where(Signature.document_id == doc.id, Signature.version_no == v.version_no)
                      .order_by(Signature.id)).scalars().all()
    return {"can_sign": can_sign_document(db, user, doc.case, doc) and v.version_no == doc.current_version
            and not any(s.signer_id == user.id for s in sigs),
            "signatures": [_signature_out(request, db, doc, v, s) for s in sigs]}


@router.post("/api/documents/{document_id}/versions/{version_no}/sign", status_code=201)
def sign_version(document_id: int, version_no: int, body: SignIn, request: Request, db: DbSession, user: User = Reader):
    """Signs the current version. The password is asked again so a signature needs the person, not just an open
    browser; a wrong password counts towards the account lockout like a failed login."""
    state = request.app.state
    doc = load_document(db, request, user, document_id)
    if not can_sign_document(db, user, doc.case, doc):
        raise HTTPException(403, "Only the department that filed this document can sign it")
    v = _get_version(doc, version_no)
    if v.version_no != doc.current_version:
        raise HTTPException(409, "Only the current version can be signed")
    _rate_limit(request, db, "password")
    _check_not_locked(db, request, user)
    if not verify_password(body.password, user.password_hash):
        _register_failure(db, request, user, "bad_password_on_sign", action="SIGN_FAILED", status=400,
                          msg="Password is incorrect", revoke_sessions_on_lock=True)
    _verified(request, db, user, doc, v)  # never put a signature on a file that has been tampered with
    if db.execute(select(Signature.id).where(Signature.document_id == doc.id, Signature.version_no == v.version_no,
                                             Signature.signer_id == user.id)).first():
        raise HTTPException(409, "You have already signed this version")
    key = signing.get_or_create_key(state, db, user)
    signed_at = utcnow()
    statement = signing.statement_for(doc, v, user, signed_at)
    sig = Signature(document_id=doc.id, version_no=v.version_no, signer_id=user.id, signed_at=signed_at,
                    statement=statement, signature=signing.sign(state, key, statement), public_key=key.public_key)
    db.add(sig)
    user.failed_attempts = 0
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "You have already signed this version")
    audit.append(db, action="DOCUMENT_SIGNED", user=user, resource_type="document", resource_id=doc.id,
                 case_number=doc.case.case_number, ip=client_ip(request),
                 detail={"version_no": v.version_no, "sha256": v.sha256, "signature_sha256": sha256_hex(sig.signature),
                         "key_ledger_tx": key.ledger_tx_id})
    db.commit()
    return _signature_out(request, db, doc, v, sig)


# ---- Section 63 certificate ---------------------------------------------------------------------------------
@router.get("/api/documents/{document_id}/versions/{version_no}/certificate")
def certificate(document_id: int, version_no: int, request: Request, db: DbSession, user: User = CustodyReader):
    """The facts a Section 63(4) Bharatiya Sakshya Adhiniyam certificate (formerly Section 65B(4) of the Indian
    Evidence Act) needs - the electronic record, how and by whom it was produced, its hash, the ledger entry that
    proves it is unchanged, and its custody - for the app to lay out as a printable certificate. Refused for a
    version that fails its integrity check. The certificate's own hash is written to the audit log."""
    state = request.app.state
    doc = load_document(db, request, user, document_id)
    v = _get_version(doc, version_no)
    report = _verified(request, db, user, doc, v)
    case: Case = doc.case
    sigs = db.execute(select(Signature).where(Signature.document_id == doc.id, Signature.version_no == v.version_no)
                      .order_by(Signature.id)).scalars().all()
    body = {
        "issued_at": utcnow(),
        "issued_by": {"name": user.full_name, "username": user.username, "role": user.role, "rank": user.rank,
                      "station": user.station.name if user.station else None},
        "case": {"case_number": case.case_number, "title": case.title, "fir_number": case.fir_number,
                 "station": case.station.name if case.station else None, "status": case.status, "stage": case.stage},
        "document": {"id": doc.id, "uid": doc.uid, "title": doc.title, "doc_type": doc.doc_type, "version_no": v.version_no,
                     "versions": doc.current_version, "filename": v.filename, "content_type": v.content_type, "size": v.size,
                     "uploaded_by": v.uploader.full_name, "uploaded_by_username": v.uploader.username,
                     "uploaded_at": v.uploaded_at, "change_note": v.change_note},
        "integrity": {"status": report["status"], "sha256": v.sha256, "recomputed_sha256": report["recomputed_sha256"],
                      "ledger_sha256": report["ledger_sha256"], "ledger_tx_id": v.ledger_tx_id, "ledger_block": v.ledger_block,
                      "ledger": "Hyperledger Fabric (Police + Court endorsement)" if state.settings.ledger_backend == "fabric" else "in-memory test ledger",
                      "checked_at": utcnow()},
        "approval": {"status": doc.approval_status, "by": doc.approver.full_name if doc.approver else None,
                     "at": doc.approved_at, "version": doc.approved_version},
        "signatures": [_signature_out(request, db, doc, v, s) for s in sigs],
        "custody": custody_entries(db, doc),
        "system": {"name": "Secure Digital Document Management System", "hash": "SHA-256",
                   "encryption": "AES-256-GCM (per-file key)", "audit": "hash-chained audit log, head anchored on the ledger"},
    }
    digest = sha256_hex(canonical(body))
    entry = audit.append(db, action="CERTIFICATE_ISSUED", user=user, resource_type="document", resource_id=doc.id,
                         case_number=case.case_number, ip=client_ip(request),
                         detail={"version_no": v.version_no, "certificate_sha256": digest})
    db.commit()
    return {**body, "certificate_no": f"SDMS/{case.case_number}/D{doc.id}-V{v.version_no}/{entry.id}", "certificate_sha256": digest}


# ---- station-head approval of FIRs and charge sheets ---------------------------------------------------------
class ApprovalIn(BaseModel):
    decision: Literal["approve", "return"]
    note: str | None = Field(default=None, max_length=500)


@router.post("/api/documents/{document_id}/approval", response_model=DocumentOut)
def decide(document_id: int, body: ApprovalIn, request: Request, db: DbSession, user: User = Depends(require_role("officer"))):
    """The station head (or an overseeing superintendent) approves a pending FIR / charge sheet - after which the
    court side can see it - or returns it with a note saying what must be corrected."""
    doc = load_document(db, request, user, document_id, lock=True)
    if not can_approve(db, user, doc.case):
        raise HTTPException(403, "Only the station head (or an overseeing superintendent) can approve this document")
    if doc.created_by == user.id:
        raise HTTPException(403, "You cannot approve a document you filed yourself")
    if doc.approval_status != "pending":
        raise HTTPException(409, "This document is not awaiting approval")
    note = (body.note or "").strip()
    if body.decision == "return" and len(note) < 3:
        raise HTTPException(422, "Say what must be corrected when returning a document")
    new = "approved" if body.decision == "approve" else "returned"
    old = doc.approval_status
    doc.approval_status, doc.approved_by, doc.approved_at = new, user.id, utcnow()
    doc.approval_note = note or None
    if new == "approved":
        doc.approved_version = doc.current_version
    db.flush()
    edits.record(db, action="DOCUMENT_APPROVED" if new == "approved" else "DOCUMENT_RETURNED", user=user, case=doc.case,
                 document=doc, reason=note or "Approved", changes=[edits.change("Approval", old, f"{new} (version {doc.current_version})")],
                 ip=client_ip(request), detail={"version_no": doc.current_version})
    db.commit()
    return document_out(request.app.state, doc)


def approval_queue(db, user: User) -> list[dict]:
    """Documents awaiting this user's approval."""
    if user.role != "officer" or user.rank not in ("station_head", "superintendent"):
        return []
    q = (select(Document, Case).join(Case, Case.id == Document.case_id)
         .where(Document.approval_status == "pending", Document.created_by != user.id))
    if user.rank == "station_head":
        q = q.where(Case.station_id == user.station_id)
    else:
        q = q.where(Case.station_id.in_(select(StationOversight.station_id).where(StationOversight.user_id == user.id)))
    return [{"document_id": d.id, "title": d.title, "doc_type": d.doc_type, "case_id": c.id, "case_number": c.case_number,
             "filed_by": d.creator.username, "filed_at": d.created_at}
            for d, c in db.execute(q.order_by(Document.id.desc()).limit(100)).all()]


@router.get("/api/approvals")
def pending_approvals(db: DbSession, user: User = Depends(require_role("officer"))):
    return approval_queue(db, user)
