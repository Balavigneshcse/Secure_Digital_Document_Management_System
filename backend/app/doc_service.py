"""Document ingestion (validate -> AI -> hash -> encrypt -> store -> anchor) and verification.

Stores involved: PostgreSQL (version row), MongoDB (encrypted blob in GridFS + document metadata) and the
Fabric ledger. They can't share a transaction, so `store_version` cleans up after itself on failure and
`commit_or_compensate` undoes the external writes if the final PostgreSQL commit fails."""
from __future__ import annotations

import hashlib
import os
import re

from cryptography.exceptions import InvalidTag
from fastapi import HTTPException, UploadFile
from sqlalchemy.orm import Session

from . import audit, docstore
from .ai import AIResult, AIServiceError
from .antivirus import ScanError
from .crypto import decrypt_file, encrypt_file
from .db import utcnow
from .models import DOC_TYPES, Case, Document, DocumentVersion, User

# extension -> (content type, magic-byte prefixes or None)
ALLOWED: dict[str, tuple[str, tuple[bytes, ...] | None]] = {
    ".pdf": ("application/pdf", (b"%PDF-",)),
    ".txt": ("text/plain", None),
    ".png": ("image/png", (b"\x89PNG\r\n\x1a\n",)),
    ".jpg": ("image/jpeg", (b"\xff\xd8\xff",)),
    ".jpeg": ("image/jpeg", (b"\xff\xd8\xff",)),
    ".tif": ("image/tiff", (b"II*\x00", b"MM\x00*")),
    ".tiff": ("image/tiff", (b"II*\x00", b"MM\x00*")),
    ".docx": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", (b"PK\x03\x04",)),
}
MAX_OCR_CHARS = 500_000
_TYPE_ALIASES = {"chargesheet": "charge_sheet"}


def safe_filename(name: str) -> str:
    base = os.path.basename((name or "").replace("\\", "/"))
    base = re.sub(r"[^\w.\- ()]", "_", base, flags=re.UNICODE).strip(" .")
    return base[:200] or "document"


def validate_upload(filename: str, data: bytes) -> tuple[str, str]:
    name = safe_filename(filename)
    ext = os.path.splitext(name)[1].lower()
    if ext not in ALLOWED:
        raise HTTPException(415, f"File type '{ext or 'unknown'}' is not allowed. Allowed: {', '.join(sorted(ALLOWED))}")
    if not data:
        raise HTTPException(400, "File is empty")
    ctype, magics = ALLOWED[ext]
    if magics and not any(data.startswith(m) for m in magics):
        raise HTTPException(415, "File content does not match its extension")
    if ctype == "text/plain" and b"\x00" in data:
        raise HTTPException(415, "File content does not match its extension")
    return name, ctype


def read_upload(upload: UploadFile, max_bytes: int) -> bytes:
    data = upload.file.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise HTTPException(413, f"File exceeds the {max_bytes // (1024 * 1024)} MB limit")
    return data


def normalise_doc_type(t: str | None) -> str:
    t = _TYPE_ALIASES.get((t or "").lower(), (t or "").lower())
    return t if t in DOC_TYPES else "other"


def _antivirus(state, db: Session, user: User, case: Case, filename: str, data: bytes) -> None:
    """Rejects an upload the scanner flags (an audited alert), and - when configured to - one it could not scan."""
    if state.av is None:
        return
    try:
        signature = state.av.scan(data)
    except ScanError as exc:
        if state.settings.clamav_required:
            raise HTTPException(503, "The virus scanner is unavailable, so the upload was refused.") from exc
        return  # scanning is best-effort unless SDMS_CLAMAV_REQUIRED
    if signature:
        db.rollback()  # discard the half-created document
        audit.append(db, action="UPLOAD_REJECTED_MALWARE", user=user, outcome="alert", resource_type="case", resource_id=case.id,
                     case_number=case.case_number, detail={"signature": signature[:80], "filename": filename,
                                                           "sha256": hashlib.sha256(data).hexdigest()})
        db.commit()
        raise HTTPException(422, f"File rejected: malware detected ({signature}).")


def _run_ai(ai, filename: str, ctype: str, data: bytes) -> tuple[AIResult, str]:
    """AI is best-effort: an unavailable service must never block filing a document."""
    try:
        res = ai.process(filename, ctype, data)
        return res, res.engine or ai.name
    except AIServiceError as exc:
        return AIResult(), f"unavailable ({exc})"[:64]


def store_version(
    state, db: Session, user: User, case: Case, doc: Document, upload: UploadFile, change_note: str | None
) -> DocumentVersion:
    data = read_upload(upload, state.settings.max_upload_mb * 1024 * 1024)
    filename, ctype = validate_upload(upload.filename or "", data)
    _antivirus(state, db, user, case, filename, data)
    ai, provider = _run_ai(state.ai, filename, ctype, data)

    version_no = doc.current_version + 1
    prev = doc.versions[-1] if doc.versions else None
    sha = hashlib.sha256(data).hexdigest()
    storage_key = os.urandom(16).hex()
    blob, wrapped = encrypt_file(state.kek, data, storage_key)
    now = utcnow()

    state.storage.put(storage_key, blob)
    meta_written = False
    try:
        block = state.ledger.anchor(
            "DOC_VERSION",
            {
                "document_uid": doc.uid, "document_id": doc.id, "version_no": version_no, "case_number": case.case_number,
                "sha256": sha, "size": len(data), "uploader_id": user.id, "uploaded_at": now,
                "prev_sha256": prev.sha256 if prev else None,
            },
        )
        doc_type = normalise_doc_type(ai.doc_type)
        entities = {k: list(v)[:25] for k, v in (ai.entities or {}).items()}
        docstore.put_meta(
            state.mongo, state.kek, document_id=doc.id, version_no=version_no, case_number=case.case_number,
            case_id=case.id, uploaded_at=now, doc_type=doc_type, doc_confidence=ai.doc_confidence,
            provider=provider, tags=list(ai.tags)[:10],
            content={
                "ocr_text": (ai.text or "")[:MAX_OCR_CHARS], "language": ai.language, "ocr_confidence": ai.ocr_confidence,
                "ocr_method": ai.ocr_method, "pages": ai.pages, "needs_review": ai.needs_review,
                "entities": entities, "scores": ai.scores, "summary": None,
            },
            embedding=ai.embedding,
        )
        meta_written = True
        version = DocumentVersion(
            document_id=doc.id, version_no=version_no, filename=filename, content_type=ctype, size=len(data),
            sha256=sha, storage_key=storage_key, wrapped_dek=wrapped, uploaded_by=user.id, uploaded_at=now,
            change_note=(change_note or None) and change_note[:255],
            ledger_tx_id=block.tx_id or block.block_hash, ledger_block=block.index,
            ai_doc_type=doc_type, ai_confidence=ai.doc_confidence, ai_provider=provider,
        )
        doc.versions.append(version)  # via the relationship so the loaded collection stays in sync
        doc.current_version = version_no
        db.flush()
        return version
    except HTTPException:
        _cleanup(state, doc.id, version_no, storage_key, meta_written)
        raise
    except Exception as exc:
        _cleanup(state, doc.id, version_no, storage_key, meta_written)
        raise HTTPException(503, "Integrity ledger or metadata store unavailable; document was not stored") from exc


def _cleanup(state, document_id: int, version_no: int, storage_key: str, meta_written: bool) -> None:
    try:
        state.storage.delete(storage_key)
        if meta_written:
            docstore.delete_meta(state.mongo, document_id, version_no)
    except Exception:  # best effort: an orphaned blob is unreachable (no DB row points at it)
        pass


def commit_or_compensate(state, db: Session, version: DocumentVersion) -> None:
    """Final PostgreSQL commit; if it fails, remove the blob and Mongo record so nothing is orphaned."""
    doc_id, version_no, key = version.document_id, version.version_no, version.storage_key
    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        _cleanup(state, doc_id, version_no, key, True)
        raise HTTPException(503, "Could not record the document; nothing was stored") from exc


def verify_version(state, doc: Document, v: DocumentVersion, *, want_bytes: bool = False):
    """Re-derives the file hash from encrypted storage and compares it with both the database
    record and the ledger entry. Returns (report dict, plaintext or None)."""
    reasons: list[str] = []
    plaintext: bytes | None = None
    recomputed: str | None = None

    if not state.storage.exists(v.storage_key):
        reasons.append("Encrypted file is missing from storage")
    else:
        try:
            plaintext = decrypt_file(state.kek, state.storage.get(v.storage_key), v.wrapped_dek, v.storage_key)
            recomputed = hashlib.sha256(plaintext).hexdigest()
        except (InvalidTag, ValueError, FileNotFoundError):
            reasons.append("Stored file failed authenticated decryption (ciphertext or key was modified)")
    if recomputed is not None and recomputed != v.sha256:
        reasons.append("File hash differs from the hash recorded at upload")

    block = state.ledger.get_by_tx(v.ledger_tx_id) if v.ledger_tx_id else None
    ledger_sha = None
    if block is None:
        reasons.append("No ledger record found for this version")
    else:
        ledger_sha = block.payload.get("sha256")
        if not state.ledger.verify_record(block):
            reasons.append("Ledger record failed its own integrity check")
        if (block.payload.get("document_uid") != doc.uid or block.payload.get("document_id") != doc.id
                or block.payload.get("version_no") != v.version_no):
            reasons.append("Ledger record belongs to a different document version")
        if ledger_sha != v.sha256:
            reasons.append("Database hash differs from the hash anchored on the ledger")
        if recomputed is not None and ledger_sha != recomputed:
            reasons.append("File hash differs from the hash anchored on the ledger")

    report = {
        "document_id": doc.id, "version_no": v.version_no,
        "status": "verified" if not reasons else "tampered", "reasons": reasons,
        "stored_sha256": v.sha256, "recomputed_sha256": recomputed, "ledger_sha256": ledger_sha,
        "ledger_tx_id": v.ledger_tx_id, "ledger_block": block.index if block else None,
    }
    return report, (plaintext if want_bytes and not reasons else None)


def _version_dict(v: DocumentVersion, content: dict | None) -> dict:
    c = content or {}
    return {
        "version_no": v.version_no, "filename": v.filename, "content_type": v.content_type, "size": v.size,
        "sha256": v.sha256, "uploaded_by": v.uploader.username, "uploaded_at": v.uploaded_at,
        "change_note": v.change_note, "ledger_tx_id": v.ledger_tx_id, "ledger_block": v.ledger_block,
        "ai_doc_type": v.ai_doc_type, "ai_confidence": v.ai_confidence, "ai_provider": v.ai_provider,
        "ai_tags": c.get("_tags", []), "ai_entities": c.get("entities", {}),
        "language": c.get("language"), "ocr_confidence": c.get("ocr_confidence"),
        "ocr_method": c.get("ocr_method"), "needs_review": bool(c.get("needs_review", False)),
        "summary": c.get("summary"),
    }


def document_out(state, doc: Document) -> dict:
    """Decrypts stored metadata for the versions of `doc` - callers must already have authorised content access."""
    keys = [docstore.meta_key(doc.id, v.version_no) for v in doc.versions]
    contents = docstore.load_contents(state.mongo, state.kek, keys)
    return {
        "id": doc.id, "uid": doc.uid, "case_id": doc.case_id, "case_number": doc.case.case_number, "title": doc.title,
        "doc_type": doc.doc_type, "description": doc.description, "created_at": doc.created_at,
        "current_version": doc.current_version,
        "versions": [_version_dict(v, contents.get(docstore.meta_key(doc.id, v.version_no))) for v in doc.versions],
    }
