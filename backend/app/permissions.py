"""Case-scoped authorisation.

Least privilege by design:
  * officer  (rank=officer)         - content access (view/upload/download) only on cases they are assigned to
  * officer  (rank=station_head)    - the above, PLUS content access to every case at their own station
  * officer  (rank=superintendent)  - the above, PLUS content access to every case at every station in `station_oversight`
  * admin    - case metadata + assignments for their own station; never document content
  * auditor  - no case or document access; audit log and ledger only
  * judge    (rank=officer)         - content access ONLY on cases explicitly shared with them (`CaseShare`); read-only
  * judge    (rank=district_court)  - the above, PLUS full read access to every case at every station in their district
  * judge    (rank=high_court)      - full read access to every case, every district
  * forensic - CAN ENTER only a case explicitly shared with them, and only if their lab's district matches the
               case's station (enforced when the share is granted, not re-checked here). Within that case they can
               upload new documents, but can open/download/verify only documents *they themselves* uploaded - an
               officer's existing investigation files stay invisible to them. Never triggers AI actions.
Requests for a case/document a user may not access get a 404, and the attempt is written to the audit log.
"""
from __future__ import annotations

from fastapi import HTTPException, Request
from sqlalchemy import exists, false, or_, select, true
from sqlalchemy.orm import Session

from . import audit
from .deps import client_ip
from .models import Case, CaseAssignment, CaseShare, Document, Station, StationOversight, User


def is_assigned(db: Session, user: User, case_id: int) -> bool:
    return (
        db.execute(
            select(CaseAssignment.id).where(CaseAssignment.case_id == case_id, CaseAssignment.user_id == user.id)
        ).first()
        is not None
    )


def oversees(db: Session, user: User, station_id: int | None) -> bool:
    """True if a rank=superintendent officer's oversight list includes this station."""
    if station_id is None:
        return False
    return (
        db.execute(
            select(StationOversight.id).where(StationOversight.user_id == user.id, StationOversight.station_id == station_id)
        ).first()
        is not None
    )


def is_shared(db: Session, user: User, case_id: int) -> bool:
    return (
        db.execute(
            select(CaseShare.id).where(CaseShare.case_id == case_id, CaseShare.shared_with_id == user.id)
        ).first()
        is not None
    )


def _station_district_id(db: Session, station_id: int | None) -> int | None:
    if station_id is None:
        return None
    return db.execute(select(Station.district_id).where(Station.id == station_id)).scalar_one_or_none()


def in_district_court(db: Session, user: User, case: Case) -> bool:
    """True if a rank=district_court/high_court judge's court reaches this case."""
    if user.rank == "high_court":
        return True
    if user.rank == "district_court":
        return user.district_id is not None and user.district_id == _station_district_id(db, case.station_id)
    return False


def can_read_content(db: Session, user: User, case: Case) -> bool:
    """Case-level 'in scope' gate: can see the case, its document list (subject to further per-document
    filtering - see `can_read_document`), and, where the role allows writing, upload to it."""
    if user.role == "officer":
        if is_assigned(db, user, case.id):
            return True
        if user.rank == "station_head":
            return user.station_id is not None and user.station_id == case.station_id
        if user.rank == "superintendent":
            return oversees(db, user, case.station_id)
        return False
    if user.role == "judge":
        return in_district_court(db, user, case) or is_shared(db, user, case.id)
    if user.role == "forensic":
        return is_shared(db, user, case.id)
    return False


def can_read_document(db: Session, user: User, case: Case, doc: Document) -> bool:
    """Document-level gate. Identical to `can_read_content` for every role except forensic, who may open
    only documents they uploaded themselves - never an officer's existing investigation files."""
    if user.role == "forensic":
        return is_shared(db, user, case.id) and doc.created_by == user.id
    return can_read_content(db, user, case)


def can_view_case(db: Session, user: User, case: Case) -> bool:
    if user.role in ("officer", "forensic", "judge"):
        return can_read_content(db, user, case)  # for these roles, "view" and "content" are the same threshold
    if user.role == "admin":
        return user.station_id is not None and user.station_id == case.station_id
    return False


def content_scope(user: User):
    """A SQLAlchemy boolean expression, true for a `Case` row the user has content (case-level) access to. For
    use in list/search queries already selecting from (or joined to) `Case` - e.g. `.where(content_scope(user))`.
    Must stay logically equivalent to `can_read_content` above; `test_permissions.py` checks the two agree."""
    if user.role == "officer":
        conditions = [exists().where(CaseAssignment.case_id == Case.id, CaseAssignment.user_id == user.id)]
        if user.rank == "station_head" and user.station_id is not None:
            conditions.append(Case.station_id == user.station_id)
        elif user.rank == "superintendent":
            conditions.append(exists().where(StationOversight.user_id == user.id, StationOversight.station_id == Case.station_id))
        return or_(*conditions)
    if user.role == "judge":
        conditions = [exists().where(CaseShare.case_id == Case.id, CaseShare.shared_with_id == user.id)]
        if user.rank == "high_court":
            conditions.append(true())
        elif user.rank == "district_court" and user.district_id is not None:
            conditions.append(
                exists().where(Station.id == Case.station_id, Station.district_id == user.district_id)
            )
        return or_(*conditions)
    if user.role == "forensic":
        return exists().where(CaseShare.case_id == Case.id, CaseShare.shared_with_id == user.id)
    return false()


def _deny(db: Session, request: Request, user: User, case_number: str | None, rtype: str, rid, reason: str):
    db.rollback()
    audit.append(
        db, action="ACCESS_DENIED", user=user, outcome="denied", resource_type=rtype, resource_id=rid,
        case_number=case_number, ip=client_ip(request),
        detail={"endpoint": f"{request.method} {request.url.path}", "reason": reason},
    )
    db.commit()
    raise HTTPException(404, "Not found")


def load_case(db: Session, request: Request, user: User, case_id: int, *, content: bool) -> Case:
    """Loads a case the user may access, else 404 (+ audit). `content=True` demands content rights."""
    case = db.get(Case, case_id)
    if case is None:
        raise HTTPException(404, "Not found")
    ok = can_read_content(db, user, case) if content else can_view_case(db, user, case)
    if not ok:
        _deny(db, request, user, case.case_number, "case", case.id, "not assigned / out of scope")
    return case


def load_document(
    db: Session, request: Request, user: User, document_id: int, *, content: bool = True, lock: bool = False
) -> Document:
    doc = db.get(Document, document_id, with_for_update=lock)
    if doc is None:
        raise HTTPException(404, "Not found")
    case = doc.case
    ok = can_read_document(db, user, case, doc) if content else can_view_case(db, user, case)
    if not ok:
        _deny(db, request, user, case.case_number, "document", doc.id, "not assigned / out of scope")
    return doc
