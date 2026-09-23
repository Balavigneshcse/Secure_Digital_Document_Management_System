from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select

from pydantic import BaseModel

from .. import audit, docstore
from ..ai import AIServiceError
from ..db import advisory_xact_lock
from ..deps import DbSession, client_ip, require_role
from ..models import Case, CaseAssignment, CaseParty, CaseShare, Document, Station, User
from ..permissions import can_read_content, content_scope, load_case
from ..schemas import AssignIn, CaseCreate, CaseOut, ShareIn

router = APIRouter(prefix="/api/cases", tags=["cases"])
CaseUser = Depends(require_role("officer", "admin"))  # create a case
CaseViewer = Depends(require_role("officer", "admin", "forensic", "judge"))  # list / view a case


def case_out(db, user: User, case: Case) -> CaseOut:
    doc_count = None
    if can_read_content(db, user, case):
        doc_count = db.scalar(select(func.count(Document.id)).where(Document.case_id == case.id))
    return CaseOut(
        id=case.id, case_number=case.case_number, fir_number=case.fir_number, title=case.title,
        case_type=case.case_type, description=case.description, status=case.status,
        station_id=case.station_id, created_at=case.created_at,
        parties=[{"name": p.name, "role": p.role} for p in case.parties],
        assignees=[
            {"user_id": a.user_id, "username": a.user.username, "full_name": a.user.full_name} for a in case.assignments
        ],
        shares=[
            {"user_id": s.shared_with_id, "username": s.shared_with.username, "full_name": s.shared_with.full_name,
             "role": s.shared_with.role, "shared_by": s.granter.username, "created_at": s.created_at}
            for s in case.shares
        ],
        document_count=doc_count,
    )


def _station_officer(db, admin: User, user_id: int) -> User:
    u = db.get(User, user_id)
    if u is None or u.role != "officer" or u.station_id != admin.station_id or not u.is_active:
        raise HTTPException(400, f"User {user_id} is not an active officer of your station")
    return u


def _reviewer(db, user_id: int) -> User:
    """A forensic/judge account, valid as a share target regardless of who is granting the share."""
    u = db.get(User, user_id)
    if u is None or u.role not in ("forensic", "judge") or not u.is_active:
        raise HTTPException(400, f"User {user_id} is not an active forensic or judge account")
    return u


@router.get("", response_model=list[CaseOut])
def list_cases(db: DbSession, user: User = CaseViewer):
    q = select(Case).order_by(Case.id.desc())
    if user.role == "admin":
        q = q.where(Case.station_id == user.station_id)
    else:  # officer (assigned, or station-wide by rank), forensic, judge (shared)
        q = q.where(content_scope(user))
    return [case_out(db, user, c) for c in db.execute(q).scalars()]


@router.post("", response_model=CaseOut, status_code=201)
def create_case(body: CaseCreate, request: Request, db: DbSession, user: User = CaseUser):
    if user.station_id is None:
        raise HTTPException(400, "Your account has no station")
    if body.officer_ids and user.role != "admin":
        raise HTTPException(403, "Only station admins can assign officers at creation")
    station = user.station
    prefix = f"CR-{datetime.now(timezone.utc).year}-{station.code}-"
    advisory_xact_lock(db, f"case-number:{prefix}")  # concurrent registrations must not draw the same number
    seq = (db.scalar(select(func.count(Case.id)).where(Case.case_number.like(f"{prefix}%"))) or 0) + 1
    case = Case(
        case_number=f"{prefix}{seq:04d}", fir_number=(body.fir_number or None), title=body.title,
        case_type=body.case_type, description=body.description, station_id=user.station_id, created_by=user.id,
    )
    case.parties = [CaseParty(name=p.name, role=p.role) for p in body.parties]
    assignees = [user] if user.role == "officer" else [_station_officer(db, user, i) for i in dict.fromkeys(body.officer_ids)]
    case.assignments = [CaseAssignment(user_id=u.id, assigned_by=user.id) for u in assignees]
    db.add(case)
    db.flush()
    audit.append(db, action="CASE_CREATED", user=user, resource_type="case", resource_id=case.id,
                 case_number=case.case_number, ip=client_ip(request),
                 detail={"assignees": [u.username for u in assignees]})
    db.commit()
    return case_out(db, user, case)


@router.get("/{case_id}", response_model=CaseOut)
def get_case(case_id: int, request: Request, db: DbSession, user: User = CaseViewer):
    case = load_case(db, request, user, case_id, content=False)
    audit.append(db, action="CASE_VIEWED", user=user, resource_type="case", resource_id=case.id,
                 case_number=case.case_number, ip=client_ip(request))
    db.commit()
    return case_out(db, user, case)


class CaseSummaryOut(BaseModel):
    available: bool
    overall: str | None = None
    by_type: dict[str, str] = {}
    documents: int = 0


@router.post("/{case_id}/summary", response_model=CaseSummaryOut)
def summarize_case(case_id: int, request: Request, db: DbSession, user: User = Depends(require_role("officer"))):
    """On-demand overview of a case from the extracted text of its documents, written by the local LLM."""
    state = request.app.state
    case = load_case(db, request, user, case_id, content=True)
    docs = db.execute(select(Document).where(Document.case_id == case.id).order_by(Document.id)).scalars().all()
    contents = docstore.load_contents(state.mongo, state.kek, [docstore.meta_key(d.id, d.current_version) for d in docs])
    payload = []
    for d in docs:
        text = (contents.get(docstore.meta_key(d.id, d.current_version)) or {}).get("ocr_text") or ""
        if text.strip():
            payload.append({"text": text[:20000], "doc_type": d.doc_type})
    if not payload:
        raise HTTPException(422, "None of this case's documents has extracted text to summarise")
    try:
        result = state.ai.summarize_case(payload[:12])
    except AIServiceError as exc:
        raise HTTPException(503, f"AI service unavailable: {exc}")
    audit.append(db, action="CASE_SUMMARISED", user=user, resource_type="case", resource_id=case.id,
                 case_number=case.case_number, ip=client_ip(request), detail={"documents": len(payload), "available": bool(result)})
    db.commit()
    if not result or not result.get("overall"):  # no AI, or every statement it wrote failed the grounding check
        return CaseSummaryOut(available=False, documents=len(payload))
    return CaseSummaryOut(available=True, overall=result.get("overall"), by_type=result.get("by_type") or {}, documents=len(payload))


@router.post("/{case_id}/assignments", response_model=CaseOut)
def assign(case_id: int, body: AssignIn, request: Request, db: DbSession, admin: User = Depends(require_role("admin"))):
    case = load_case(db, request, admin, case_id, content=False)
    officer = _station_officer(db, admin, body.user_id)
    if any(a.user_id == officer.id for a in case.assignments):
        raise HTTPException(409, "Officer is already assigned to this case")
    case.assignments.append(CaseAssignment(user_id=officer.id, assigned_by=admin.id))
    db.flush()
    audit.append(db, action="CASE_ASSIGNED", user=admin, resource_type="case", resource_id=case.id,
                 case_number=case.case_number, ip=client_ip(request), detail={"officer": officer.username})
    db.commit()
    return case_out(db, admin, case)


@router.delete("/{case_id}/assignments/{user_id}", response_model=CaseOut)
def unassign(case_id: int, user_id: int, request: Request, db: DbSession, admin: User = Depends(require_role("admin"))):
    case = load_case(db, request, admin, case_id, content=False)
    a = next((x for x in case.assignments if x.user_id == user_id), None)
    if a is None:
        raise HTTPException(404, "Assignment not found")
    officer_name = a.user.username
    case.assignments.remove(a)
    db.flush()
    audit.append(db, action="CASE_UNASSIGNED", user=admin, resource_type="case", resource_id=case.id,
                 case_number=case.case_number, ip=client_ip(request), detail={"officer": officer_name})
    db.commit()
    return case_out(db, admin, case)


# ---- sharing with forensic / judge accounts (read-only, per-case, no expiry yet) -----------------
ShareGranter = Depends(require_role("officer", "admin"))


@router.post("/{case_id}/shares", response_model=CaseOut, status_code=201)
def share(case_id: int, body: ShareIn, request: Request, db: DbSession, user: User = ShareGranter):
    # Officers must be able to see the content they're sharing; admins share administratively, same as
    # assignment, without needing content access themselves.
    case = load_case(db, request, user, case_id, content=(user.role == "officer"))
    target = _reviewer(db, body.user_id)
    if target.role == "forensic" and target.district_id is not None:
        # Only enforced once the lab actually has a home district - an undistricted case/lab predates districts
        # entirely and is left alone (see District's docstring: optional, unaffected if unset).
        case_district = db.execute(select(Station.district_id).where(Station.id == case.station_id)).scalar_one_or_none()
        if case_district is not None and target.district_id != case_district:
            raise HTTPException(400, f"{target.username}'s forensic lab is not in this case's district")
    if any(s.shared_with_id == target.id for s in case.shares):
        raise HTTPException(409, f"{target.username} already has access to this case")
    case.shares.append(CaseShare(shared_with_id=target.id, shared_by=user.id))
    db.flush()
    audit.append(db, action="CASE_SHARED", user=user, resource_type="case", resource_id=case.id,
                 case_number=case.case_number, ip=client_ip(request),
                 detail={"shared_with": target.username, "role": target.role})
    db.commit()
    return case_out(db, user, case)


@router.delete("/{case_id}/shares/{user_id}", response_model=CaseOut)
def unshare(case_id: int, user_id: int, request: Request, db: DbSession, user: User = ShareGranter):
    case = load_case(db, request, user, case_id, content=(user.role == "officer"))
    s = next((x for x in case.shares if x.shared_with_id == user_id), None)
    if s is None:
        raise HTTPException(404, "Share not found")
    target_name = s.shared_with.username
    case.shares.remove(s)
    db.flush()
    audit.append(db, action="CASE_UNSHARED", user=user, resource_type="case", resource_id=case.id,
                 case_number=case.case_number, ip=client_ip(request), detail={"revoked_from": target_name})
    db.commit()
    return case_out(db, user, case)
