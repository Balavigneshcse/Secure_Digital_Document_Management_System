from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import case as sa_case
from sqlalchemy import exists, or_, select

from .. import audit, docstore
from ..ai import AIServiceError
from ..deps import DbSession, client_ip, require_role
from ..models import Case, CaseParty, Document, DocumentVersion, User
from ..permissions import content_scope

router = APIRouter(prefix="/api/search", tags=["search"])
DATE = r"^\d{4}-\d{2}-\d{2}$"
MAX_CANDIDATES = 5000


def _like(term: str) -> str:
    return "%" + term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def _ilike(col, term: str):
    return col.ilike(_like(term), escape="\\")


def _snippet(text: str | None, term: str | None, width: int = 80) -> str | None:
    if not text:
        return None
    if term:
        for w in sorted(term.split(), key=len, reverse=True):
            i = text.lower().find(w.lower())
            if i >= 0:
                s = max(0, i - width)
                return ("…" if s else "") + text[s : i + len(w) + width].replace("\n", " ") + "…"
    return text[: 2 * width].replace("\n", " ")


@router.get("")
def search(
    request: Request,
    db: DbSession,
    q: str | None = Query(None, max_length=200),
    case_number: str | None = Query(None, max_length=48),
    fir_number: str | None = Query(None, max_length=64),
    party: str | None = Query(None, max_length=120, description="Party name or a person named in a document"),
    doc_type: str | None = Query(None, max_length=32),
    date_from: str | None = Query(None, pattern=DATE, description="Document filed on/after (YYYY-MM-DD)"),
    date_to: str | None = Query(None, pattern=DATE, description="Document filed on/before (YYYY-MM-DD)"),
    semantic: bool = Query(False, description="Rank by meaning (embeddings) instead of matching words"),
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: User = Depends(require_role("officer", "admin", "forensic", "judge")),
):
    """Officers, and forensic/judge accounts on cases shared with them, search cases and documents (incl.
    OCR'd content) within their content scope. Station admins search case metadata only; document
    titles/content are never exposed to them.

    Whole-word matching: document text is stored encrypted and searched through a keyed blind index, so
    substring / prefix queries over document *content* are not supported (title and case fields are)."""
    state = request.app.state
    has_content = user.role != "admin"
    party_match = lambda t: exists().where(CaseParty.case_id == Case.id, _ilike(CaseParty.name, t))  # noqa: E731

    # ---- cases (PostgreSQL) ----
    cq = select(Case)
    if user.role == "admin":
        cq = cq.where(Case.station_id == user.station_id)
    else:
        cq = cq.where(content_scope(user))
    if q:
        cq = cq.where(or_(_ilike(Case.title, q), _ilike(Case.description, q), _ilike(Case.case_number, q),
                          _ilike(Case.fir_number, q), party_match(q)))
    if case_number:
        cq = cq.where(_ilike(Case.case_number, case_number))
    if fir_number:
        cq = cq.where(_ilike(Case.fir_number, fir_number))
    if party:
        cq = cq.where(party_match(party))
    cases = db.execute(cq.order_by(Case.id.desc()).limit(limit)).scalars().unique().all()
    case_hits = [
        {"id": c.id, "case_number": c.case_number, "fir_number": c.fir_number, "title": c.title,
         "case_type": c.case_type, "status": c.status, "parties": [p.name for p in c.parties]}
        for c in cases
    ]

    # ---- documents (content-scope roles only: officer, forensic, judge - never admin) ----
    doc_hits, doc_total, mode = [], None, "none"
    if has_content:
        if semantic and not q:
            raise HTTPException(422, "semantic search needs q")
        # 1. permission-scoped candidates + structured filters, in PostgreSQL
        dq = (
            select(
                Document.id, Document.title, Document.doc_type, Document.current_version, Case.id.label("case_id"),
                Case.case_number, DocumentVersion.uploaded_at,
                (sa_case((or_(_ilike(Document.title, q), _ilike(Document.description, q), _ilike(Case.case_number, q),
                              _ilike(Case.fir_number, q), party_match(q)), True), else_=False) if q else sa_case((Document.id > 0, True), else_=True)).label("pg_q"),
                (sa_case((party_match(party), True), else_=False) if party else sa_case((Document.id > 0, True), else_=True)).label("pg_party"),
            )
            .join(Case, Case.id == Document.case_id)
            .join(DocumentVersion, (DocumentVersion.document_id == Document.id) & (DocumentVersion.version_no == Document.current_version))
            .where(content_scope(user))
        )
        if case_number:
            dq = dq.where(_ilike(Case.case_number, case_number))
        if fir_number:
            dq = dq.where(_ilike(Case.fir_number, fir_number))
        if doc_type:
            dq = dq.where(Document.doc_type == doc_type)
        if date_from:
            dq = dq.where(DocumentVersion.uploaded_at >= date_from)
        if date_to:
            dq = dq.where(DocumentVersion.uploaded_at <= date_to + "T23:59:59.999999Z")
        rows = db.execute(dq.order_by(DocumentVersion.uploaded_at.desc()).limit(MAX_CANDIDATES)).all()
        keys = {docstore.meta_key(r.id, r.current_version): r for r in rows}
        key_list = list(keys)

        # 2. text conditions: PostgreSQL columns OR the encrypted-content blind index in MongoDB
        keep = dict(keys)
        scores: dict[str, float] = {}
        if q and semantic:
            mode = "semantic"
            try:
                qvec = state.ai.embed(q)
            except AIServiceError as exc:
                raise HTTPException(503, f"AI service unavailable: {exc}")
            if not qvec:
                raise HTTPException(503, "Semantic search needs the AI service (no embedding available)")
            scores = dict(docstore.semantic_top(state.mongo, key_list, qvec, k=limit + offset))
            keep = {k: keys[k] for k in scores}
        else:
            if q:
                mode = "keyword"
                hit = docstore.keyword_matches(state.mongo, state.kek, key_list, q)
                keep = {k: r for k, r in keep.items() if r.pg_q or k in hit}
            if party:
                hit = docstore.keyword_matches(state.mongo, state.kek, list(keep), party)
                keep = {k: r for k, r in keep.items() if r.pg_party or k in hit}
        ordered = sorted(keep, key=lambda k: -scores[k]) if scores else list(keep)
        doc_total = len(ordered)
        page = ordered[offset : offset + limit]
        contents = docstore.load_contents(state.mongo, state.kek, page)
        for k in page:
            r = keys[k]
            doc_hits.append({
                "document_id": r.id, "title": r.title, "doc_type": r.doc_type, "case_id": r.case_id,
                "case_number": r.case_number, "version_no": r.current_version, "uploaded_at": r.uploaded_at,
                "snippet": _snippet((contents.get(k) or {}).get("ocr_text"), q or party),
                "score": round(scores[k], 3) if k in scores else None,
            })

    params = {k: v for k, v in dict(q=q, case_number=case_number, fir_number=fir_number, party=party,
                                    doc_type=doc_type, date_from=date_from, date_to=date_to,
                                    semantic=semantic or None).items() if v}
    audit.append(db, action="SEARCH", user=user, ip=client_ip(request),
                 detail={"params": params, "mode": mode, "cases": len(case_hits), "documents": len(doc_hits)})
    db.commit()
    return {"cases": case_hits, "documents": doc_hits, "documents_total": doc_total, "mode": mode}
