from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select

from .. import audit, docstore
from ..ai import AIServiceError
from ..db import utcnow
from ..deps import DbSession, client_ip, require_role
from ..netutil import enforce
from ..doc_service import commit_or_compensate, document_out, normalise_doc_type, store_version, verify_version
from ..models import DOC_TYPES, Case, Document, User
from ..permissions import load_case, load_document
from ..schemas import DocumentOut, VerifyOut, valid_doc_type

router = APIRouter(tags=["documents"])
Officer = Depends(require_role("officer"))  # new version, AI summary/feedback: officers only
Uploader = Depends(require_role("officer", "forensic"))  # file a new document: officers, + forensic on shared cases
ContentViewer = Depends(require_role("officer", "forensic", "judge"))  # read: scoped by permissions.can_read_document


def _tamper_alert(db, request: Request, user: User, doc: Document, report: dict):
    """Records the mismatch as its own audit event (committed even though the request fails)."""
    db.rollback()
    audit.append(
        db, action="TAMPER_DETECTED", user=user, outcome="alert", resource_type="document", resource_id=doc.id,
        case_number=doc.case.case_number, ip=client_ip(request),
        detail={"version_no": report["version_no"], "reasons": report["reasons"]},
    )
    db.commit()


def _get_version(doc: Document, version_no: int):
    v = next((x for x in doc.versions if x.version_no == version_no), None)
    if v is None:
        raise HTTPException(404, "Not found")
    return v


@router.get("/api/cases/{case_id}/documents", response_model=list[DocumentOut])
def list_documents(case_id: int, request: Request, db: DbSession, user: User = ContentViewer):
    case = load_case(db, request, user, case_id, content=True)
    docs = db.execute(select(Document).where(Document.case_id == case.id).order_by(Document.id.desc())).scalars().all()
    if user.role == "forensic":  # never list an officer's investigation files, not even their titles
        docs = [d for d in docs if d.created_by == user.id]
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
    enforce(request, "upload", request.app.state.settings.upload_per_minute, key=f"user:{user.id}")
    doc = Document(case_id=case.id, title=title.strip(), doc_type="other", description=description,
                   created_by=user.id, current_version=0)
    db.add(doc)
    db.flush()
    version = store_version(request.app.state, db, user, case, doc, file, None)
    doc.doc_type = doc_type if doc_type != "auto" else (version.ai_doc_type or "other")
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


@router.post("/api/documents/{document_id}/versions", response_model=DocumentOut, status_code=201)
def upload_version(
    document_id: int,
    request: Request,
    db: DbSession,
    change_note: str | None = Form(None, max_length=255),
    file: UploadFile = File(...),
    user: User = Officer,
):
    doc = load_document(db, request, user, document_id, lock=True)  # row lock: concurrent uploads get distinct version numbers
    enforce(request, "upload", request.app.state.settings.upload_per_minute, key=f"user:{user.id}")
    version = store_version(request.app.state, db, user, doc.case, doc, file, change_note)
    audit.append(
        db, action="DOCUMENT_VERSION_ADDED", user=user, resource_type="document", resource_id=doc.id,
        case_number=doc.case.case_number, ip=client_ip(request),
        detail={"version_no": version.version_no, "sha256": version.sha256, "ledger_tx_id": version.ledger_tx_id},
    )
    commit_or_compensate(request.app.state, db, version)
    return document_out(request.app.state, doc)


@router.get("/api/documents/{document_id}/versions/{version_no}/download")
def download(document_id: int, version_no: int, request: Request, db: DbSession, user: User = ContentViewer):
    doc = load_document(db, request, user, document_id)
    v = _get_version(doc, version_no)
    report, plaintext = verify_version(request.app.state, doc, v, want_bytes=True)
    if plaintext is None:
        _tamper_alert(db, request, user, doc, report)
        raise HTTPException(409, {"message": "Integrity check failed; download blocked", "report": report})
    audit.append(
        db, action="DOCUMENT_DOWNLOADED", user=user, resource_type="document", resource_id=doc.id,
        case_number=doc.case.case_number, ip=client_ip(request), detail={"version_no": v.version_no, "sha256": v.sha256},
    )
    db.commit()
    return Response(
        content=plaintext,
        media_type=v.content_type,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(v.filename)}",
            "X-Content-SHA256": v.sha256,
        },
    )


@router.get("/api/documents/{document_id}/versions/{version_no}/verify", response_model=VerifyOut)
def verify(
    document_id: int, version_no: int, request: Request, db: DbSession,
    user: User = Depends(require_role("officer", "forensic", "judge", "auditor")),
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
    v = doc.versions[-1]
    state = request.app.state
    state.mongo.feedback.insert_one({
        "document_id": doc.id, "version_no": v.version_no, "case_number": doc.case.case_number,
        "ai_type": normalise_doc_type(v.ai_doc_type), "ai_confidence": v.ai_confidence, "correct_type": body.correct_type,
        "provider": v.ai_provider, "by": user.id, "created_at": utcnow(),
    })
    doc.doc_type = body.correct_type
    audit.append(db, action="CLASSIFICATION_CORRECTED", user=user, resource_type="document", resource_id=doc.id,
                 case_number=doc.case.case_number, ip=client_ip(request),
                 detail={"ai_type": v.ai_doc_type, "correct_type": body.correct_type})
    db.commit()
