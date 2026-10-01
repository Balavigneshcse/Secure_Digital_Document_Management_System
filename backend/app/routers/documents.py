from __future__ import annotations

import io
from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from starlette.datastructures import UploadFile as StarletteUpload

from .. import audit, docstore, edits
from ..ai import AIServiceError
from ..db import utcnow
from ..deps import DbSession, client_ip, require_role
from ..netutil import enforce
from ..doc_service import commit_or_compensate, document_out, normalise_doc_type, store_version, verify_version
from ..models import APPROVAL_TYPES, DOC_TYPES, Case, Document, User
from ..permissions import (
    SHARE_ROLES, can_edit_document, can_read_document, in_district_court, load_case, load_document, station_has_head,
)
from ..schemas import DiffOut, DocumentEdit, DocumentOut, EditOut, VerifyOut, valid_doc_type

router = APIRouter(tags=["documents"])
Officer = Depends(require_role("officer"))  # AI summary/feedback: officers only
FILERS = ("officer", "forensic", "prosecutor", "defence")
Editor = Depends(require_role(*FILERS))  # edit a document / file a new version: see can_edit_document
Uploader = Depends(require_role(*FILERS))  # file a new document: officers, + forensic/prosecutor/defence on shared cases
ContentViewer = Depends(require_role("officer", *SHARE_ROLES))  # read: scoped by permissions.can_read_document


def approval_for(db, user: User, case: Case, doc_type: str) -> str:
    """An FIR or charge sheet filed by a plain officer waits for the station head before the court side sees it.
    Stations with no station-head account have nobody to approve, so nothing is held back there."""
    if doc_type in APPROVAL_TYPES and user.role == "officer" and user.rank == "officer" and station_has_head(db, case.station_id):
        return "pending"
    return "not_required"


def _tamper_alert(db, request: Request, user: User, doc: Document, report: dict):
    """Records the mismatch as its own audit event (committed even though the request fails)."""
    db.rollback()
    audit.append(
        db, action="TAMPER_DETECTED", user=user, outcome="alert", resource_type="document", resource_id=doc.id,
        case_number=doc.case.case_number, ip=client_ip(request),
        detail={"version_no": report["version_no"], "reasons": report["reasons"]},
    )
    db.commit()


def _judge_owned(db, doc: Document) -> bool:
    """A judge's verdict is final: nobody, the filing officers included, may add a version or relabel it."""
    creator = db.get(User, doc.created_by)
    return creator is not None and creator.role == "judge"


def _get_version(doc: Document, version_no: int):
    v = next((x for x in doc.versions if x.version_no == version_no), None)
    if v is None:
        raise HTTPException(404, "Not found")
    return v


@router.get("/api/cases/{case_id}/documents", response_model=list[DocumentOut])
def list_documents(case_id: int, request: Request, db: DbSession, user: User = ContentViewer):
    case = load_case(db, request, user, case_id, content=True)
    docs = db.execute(select(Document).where(Document.case_id == case.id).order_by(Document.id.desc())).scalars().all()
    # e.g. a forensic lab never sees an officer's investigation files listed, not even their titles
    docs = [d for d in docs if can_read_document(db, user, case, d)]
    return [document_out(request.app.state, d) for d in docs]


@router.post("/api/cases/{case_id}/documents", response_model=DocumentOut, status_code=201)
def upload_document(
    case_id: int,
    request: Request,
    db: DbSession,
    title: str = Form(..., min_length=1, max_length=200),
    doc_type: str = Form("auto"),
    description: str | None = Form(None, max_length=4000),
    file: UploadFile = File(...),
    user: User = Uploader,
):
    try:
        valid_doc_type(doc_type)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    case: Case = load_case(db, request, user, case_id, content=True)
    if case.status != "open":
        raise HTTPException(409, "This case is closed; a judge must reopen it before new documents can be filed")
    enforce(request, "upload", request.app.state.settings.upload_per_minute, key=f"user:{user.id}")
    doc = Document(case_id=case.id, title=title.strip(), doc_type="other", description=description,
                   created_by=user.id, current_version=0)
    db.add(doc)
    db.flush()
    version = store_version(request.app.state, db, user, case, doc, file, None)
    doc.doc_type = doc_type if doc_type != "auto" else (version.ai_doc_type or "other")
    doc.approval_status = approval_for(db, user, case, doc.doc_type)
    audit.append(
        db, action="DOCUMENT_UPLOADED", user=user, resource_type="document", resource_id=doc.id,
        case_number=case.case_number, ip=client_ip(request),
        detail={"version_no": 1, "sha256": version.sha256, "ledger_tx_id": version.ledger_tx_id, "size": version.size,
                "ai_doc_type": version.ai_doc_type, "ai_provider": version.ai_provider},
    )
    commit_or_compensate(request.app.state, db, version)
    return document_out(request.app.state, doc)


@router.get("/api/documents/{document_id}", response_model=DocumentOut)
def get_document(document_id: int, request: Request, db: DbSession, user: User = ContentViewer):
    doc = load_document(db, request, user, document_id)
    audit.append(db, action="DOCUMENT_VIEWED", user=user, resource_type="document", resource_id=doc.id,
                 case_number=doc.case.case_number, ip=client_ip(request))
    db.commit()
    return document_out(request.app.state, doc)


def _editable(db, user: User, doc: Document) -> None:
    """403/409 unless `user` may change `doc` now (the caller has already established read access)."""
    if not can_edit_document(db, user, doc.case, doc):
        raise HTTPException(403, "A recorded verdict cannot be amended" if _judge_owned(db, doc)
                            else "Only the department that filed this document can change it")
    if doc.case.status != "open":
        raise HTTPException(409, "This case is closed; its documents can no longer be edited")


@router.patch("/api/documents/{document_id}", response_model=DocumentOut)
def edit_document(document_id: int, body: DocumentEdit, request: Request, db: DbSession, user: User = Editor):
    """Changes a document's title or description. The old and new values, the editor, the reason and the server
    time are kept in the edit history; the file itself is changed only by filing a new version."""
    doc = load_document(db, request, user, document_id, lock=True)
    _editable(db, user, doc)
    sent, changes = body.model_fields_set, []
    if "title" in sent:
        new = (body.title or "").strip()
        if not new:
            raise HTTPException(422, "Title cannot be empty")
        if new != doc.title:
            changes.append(edits.change("Title", doc.title, new))
            doc.title = new
    if "description" in sent:
        new = (body.description or "").strip() or None
        if new != doc.description:
            changes.append(edits.change("Description", doc.description, new))
            doc.description = new
    if not changes:
        raise HTTPException(400, "Nothing was changed")
    db.flush()
    edits.record(db, action="DOCUMENT_EDITED", user=user, case=doc.case, document=doc, reason=body.reason,
                 changes=changes, ip=client_ip(request))
    db.commit()
    return document_out(request.app.state, doc)


@router.get("/api/documents/{document_id}/history", response_model=list[EditOut])
def document_history(document_id: int, request: Request, db: DbSession, user: User = ContentViewer):
    """Every recorded edit to this document (details and new versions), newest first."""
    doc = load_document(db, request, user, document_id)
    return edits.history(db, doc.case, document_ids={doc.id}, include_case=False)


@router.post("/api/documents/{document_id}/versions", response_model=DocumentOut, status_code=201)
def upload_version(
    document_id: int,
    request: Request,
    db: DbSession,
    change_note: str = Form(..., min_length=3, max_length=255),
    file: UploadFile = File(...),
    user: User = Editor,
):
    """Edits a document's content. Nothing is overwritten: the file becomes a new ledger-anchored version, the
    earlier ones stay, and the mandatory note says what changed and why."""
    if len(change_note.strip()) < 3:
        raise HTTPException(422, "A change note saying what was changed and why is required")
    doc = load_document(db, request, user, document_id, lock=True)  # row lock: concurrent uploads get distinct version numbers
    _editable(db, user, doc)
    enforce(request, "upload", request.app.state.settings.upload_per_minute, key=f"user:{user.id}")
    prev = doc.versions[-1]
    version = store_version(request.app.state, db, user, doc.case, doc, file, change_note.strip())
    if doc.approval_status == "returned":
        doc.approval_status = "pending"  # resubmitted for approval
    edits.record(
        db, action="DOCUMENT_VERSION_ADDED", user=user, case=doc.case, document=doc, reason=change_note,
        changes=[edits.change("File", f"v{prev.version_no} - {prev.filename} - SHA-256 {prev.sha256}",
                              f"v{version.version_no} - {version.filename} - SHA-256 {version.sha256}")],
        ip=client_ip(request),
        detail={"version_no": version.version_no, "sha256": version.sha256, "ledger_tx_id": version.ledger_tx_id},
    )
    commit_or_compensate(request.app.state, db, version)
    return document_out(request.app.state, doc)


@router.get("/api/documents/{document_id}/versions/{version_no}/diff", response_model=DiffOut)
def version_diff(document_id: int, version_no: int, request: Request, db: DbSession, user: User = ContentViewer):
    """What changed in this version's text compared with the version before it (from the extracted text, so it
    works for scans too, as far as OCR read them)."""
    state = request.app.state
    doc = load_document(db, request, user, document_id)
    v = _get_version(doc, version_no)
    if v.version_no == 1:
        return DiffOut(from_version=1, to_version=1, available=False, note="This is the first version; there is nothing earlier to compare it with.")
    keys = [docstore.meta_key(doc.id, v.version_no - 1), docstore.meta_key(doc.id, v.version_no)]
    contents = docstore.load_contents(state.mongo, state.kek, keys)
    old, new = ((contents.get(k) or {}).get("ocr_text") or "" for k in keys)
    audit.append(db, action="DOCUMENT_DIFF_VIEWED", user=user, resource_type="document", resource_id=doc.id,
                 case_number=doc.case.case_number, ip=client_ip(request), detail={"version_no": v.version_no})
    db.commit()
    if not old.strip() or not new.strip():
        return DiffOut(from_version=v.version_no - 1, to_version=v.version_no, available=False,
                       note="No text could be extracted from one of the two versions, so they cannot be compared line by line. "
                            "Their SHA-256 hashes show whether the files differ.")
    return DiffOut(from_version=v.version_no - 1, to_version=v.version_no, available=True, **edits.text_diff(old, new))


@router.get("/api/documents/{document_id}/versions/{version_no}/download")
def download(document_id: int, version_no: int, request: Request, db: DbSession, user: User = ContentViewer,
             inline: bool = False):
    """The verified file. `inline=true` is the in-browser viewer: same integrity check, recorded as DOCUMENT_OPENED."""
    doc = load_document(db, request, user, document_id)
    v = _get_version(doc, version_no)
    report, plaintext = verify_version(request.app.state, doc, v, want_bytes=True)
    if plaintext is None:
        _tamper_alert(db, request, user, doc, report)
        raise HTTPException(409, {"message": "Integrity check failed; download blocked", "report": report})
    audit.append(
        db, action="DOCUMENT_OPENED" if inline else "DOCUMENT_DOWNLOADED", user=user, resource_type="document",
        resource_id=doc.id, case_number=doc.case.case_number, ip=client_ip(request),
        detail={"version_no": v.version_no, "sha256": v.sha256},
    )
    db.commit()
    return Response(
        content=plaintext,
        media_type=v.content_type,
        headers={
            "Content-Disposition": f"{'inline' if inline else 'attachment'}; filename*=UTF-8''{quote(v.filename)}",
            "X-Content-SHA256": v.sha256,
        },
    )


@router.get("/api/documents/{document_id}/versions/{version_no}/verify", response_model=VerifyOut)
def verify(
    document_id: int, version_no: int, request: Request, db: DbSession,
    user: User = Depends(require_role("officer", *SHARE_ROLES, "auditor")),
):
    # Auditors may check integrity of any version (no content is returned); everyone else only their own scope.
    if user.role != "auditor":
        doc = load_document(db, request, user, document_id)
    else:
        doc = db.get(Document, document_id)
        if doc is None:
            raise HTTPException(404, "Not found")
    v = _get_version(doc, version_no)
    report, _ = verify_version(request.app.state, doc, v)
    if report["status"] == "tampered":
        _tamper_alert(db, request, user, doc, report)
    else:
        audit.append(db, action="DOCUMENT_VERIFIED", user=user, resource_type="document", resource_id=doc.id,
                     case_number=doc.case.case_number, ip=client_ip(request), detail={"version_no": v.version_no})
        db.commit()
    return report


# ---- AI-assisted actions ------------------------------------------------------------------------
class SummaryOut(BaseModel):
    summary: str | None
    available: bool


@router.post("/api/documents/{document_id}/versions/{version_no}/summary", response_model=SummaryOut)
def summarize_version(document_id: int, version_no: int, request: Request, db: DbSession, user: User = Officer):
    """Summarises a version with the local LLM, on demand (LLM calls are too slow to run on every upload)."""
    state = request.app.state
    doc = load_document(db, request, user, document_id)
    v = _get_version(doc, version_no)
    contents = docstore.load_contents(state.mongo, state.kek, [docstore.meta_key(doc.id, v.version_no)])
    content = next(iter(contents.values()), None)
    if not content or not (content.get("ocr_text") or "").strip():
        raise HTTPException(422, "No extracted text is available for this version")
    try:
        summary = state.ai.summarize(content["ocr_text"])
    except AIServiceError as exc:
        raise HTTPException(503, f"AI service unavailable: {exc}")
    if summary:
        docstore.update_content(state.mongo, state.kek, doc.id, v.version_no, summary=summary)
    audit.append(db, action="DOCUMENT_SUMMARISED", user=user, resource_type="document", resource_id=doc.id,
                 case_number=doc.case.case_number, ip=client_ip(request),
                 detail={"version_no": v.version_no, "available": bool(summary)})
    db.commit()
    return SummaryOut(summary=summary, available=bool(summary))


class FeedbackIn(BaseModel):
    correct_type: str


@router.post("/api/documents/{document_id}/classification-feedback", status_code=204)
def classification_feedback(document_id: int, body: FeedbackIn, request: Request, db: DbSession, user: User = Officer):
    """Officer corrects the AI's document type. The correction updates the document and is kept as labelled
    training data for the next fine-tuning run (ai/README.md); it never contains document text."""
    if body.correct_type not in DOC_TYPES:
        raise HTTPException(422, f"correct_type must be one of {', '.join(DOC_TYPES)}")
    doc = load_document(db, request, user, document_id)
    _editable(db, user, doc)
    v = doc.versions[-1]
    state = request.app.state
    state.mongo.feedback.insert_one({
        "document_id": doc.id, "version_no": v.version_no, "case_number": doc.case.case_number,
        "ai_type": normalise_doc_type(v.ai_doc_type), "ai_confidence": v.ai_confidence, "correct_type": body.correct_type,
        "provider": v.ai_provider, "by": user.id, "created_at": utcnow(),
    })
    if doc.doc_type != body.correct_type:
        edits.record(db, action="DOCUMENT_EDITED", user=user, case=doc.case, document=doc,
                     reason="Document type corrected", changes=[edits.change("Document type", doc.doc_type, body.correct_type)],
                     ip=client_ip(request))
    doc.doc_type = body.correct_type
    if doc.approval_status == "not_required":
        doc.approval_status = approval_for(db, db.get(User, doc.created_by), doc.case, doc.doc_type)
    audit.append(db, action="CLASSIFICATION_CORRECTED", user=user, resource_type="document", resource_id=doc.id,
                 case_number=doc.case.case_number, ip=client_ip(request),
                 detail={"ai_type": v.ai_doc_type, "correct_type": body.correct_type})
    db.commit()


# ---- Judge's verdict ------------------------------------------------------------------------------
OUTCOMES = {
    "convicted": "Convicted",
    "acquitted": "Acquitted",
    "discharged": "Discharged",
    "dismissed": "Case dismissed",
    "disposed": "Disposed of",
}


class VerdictIn(BaseModel):
    outcome: Literal["convicted", "acquitted", "discharged", "dismissed", "disposed"]
    reasoning: str = Field(min_length=20, max_length=8000)
    sentence: str | None = Field(None, max_length=500)


@router.post("/api/cases/{case_id}/verdict", response_model=DocumentOut, status_code=201)
def record_verdict(
    case_id: int, body: VerdictIn, request: Request, db: DbSession,
    user: User = Depends(require_role("judge")),
):
    """A district/high court judge records the final judgment. It is filed like any other document - hashed,
    encrypted, anchored on the ledger, audited - which is what makes it tamper-evident. One verdict per case; the
    case is closed. Judges holding only a per-case share (no jurisdiction) can read a case but not decide it."""
    case: Case = load_case(db, request, user, case_id, content=True)
    if not in_district_court(db, user, case):
        raise HTTPException(403, "Only the judge of the court that has jurisdiction over this case can record a verdict")
    state = request.app.state
    enforce(request, "upload", state.settings.upload_per_minute, key=f"user:{user.id}")
    db.execute(select(Case.id).where(Case.id == case.id).with_for_update())  # two judges can't both decide it
    db.refresh(case)
    if case.status != "open":
        raise HTTPException(409, "A verdict has already been recorded for this case")
    now = utcnow()
    court = "High Court" if user.rank == "high_court" else "District Court"
    rule = "=" * 60
    lines = [
        "JUDGMENT", rule,
        f"Case number : {case.case_number}",
        f"Case title  : {case.title}",
        f"FIR number  : {case.fir_number or '-'}",
        f"Court       : {court}",
        f"Judge       : {user.full_name}",
        f"Date        : {now}",
        "",
        f"VERDICT     : {OUTCOMES[body.outcome].upper()}",
    ]
    if body.sentence and body.sentence.strip():
        lines.append(f"SENTENCE    : {body.sentence.strip()}")
    lines += ["", "REASONS", "-" * 60, body.reasoning.strip(), ""]
    text = chr(10).join(lines)
    upload = StarletteUpload(file=io.BytesIO(text.encode("utf-8")), filename=f"verdict-{case.case_number}.txt")
    doc = Document(case_id=case.id, title=f"Judgment - {OUTCOMES[body.outcome]}", doc_type="judgment",
                   description=f"Verdict recorded by {user.full_name}", created_by=user.id, current_version=0)
    db.add(doc)
    db.flush()
    version = store_version(state, db, user, case, doc, upload, None)
    case.status, case.stage = "closed", "judgment_delivered"
    audit.append(
        db, action="VERDICT_RECORDED", user=user, resource_type="document", resource_id=doc.id,
        case_number=case.case_number, ip=client_ip(request),
        detail={"outcome": body.outcome, "sha256": version.sha256, "ledger_tx_id": version.ledger_tx_id},
    )
    commit_or_compensate(state, db, version)
    return document_out(state, doc)
