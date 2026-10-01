"""Case-scoped authorisation.

Least privilege by design:
  * officer  (rank=officer)         - content access (view/upload/download) only on cases they are assigned to
  * officer  (rank=station_head)    - the above, PLUS content access to every case at their own station; approves
                                      the FIRs and charge sheets plain officers of that station file
  * officer  (rank=superintendent)  - the above, PLUS content access to every case at every station in `station_oversight`
  * admin    (rank=officer)         - case metadata + assignments for their own station; never document content
  * admin    (rank=system)          - no station, no case access at all: manages user accounts of every role
  * auditor  - no case or document access; audit log and ledger only
  * judge    (rank=officer)         - content access ONLY on cases explicitly shared with them (`CaseShare`); read-only
  * judge    (rank=district_court)  - the above, PLUS full read access to every case at every station in their district
  * judge    (rank=high_court)      - full read access to every case, every district
               Court-rank judges can also record the case's verdict and reopen a closed case (routers/documents.py).
  * prosecutor - cases explicitly shared with them: reads every court-visible document, files its own
  * forensic - CAN ENTER only a case explicitly shared with them, and only if their lab's district matches the
               case's station (enforced when the share is granted, not re-checked here). Within that case they can
               upload new documents, but can open/download/verify only documents *they themselves* uploaded - an
               officer's existing investigation files stay invisible to them. Never triggers AI actions.
  * defence  - cases explicitly shared with them: files its own documents, and reads only what the defence is
               entitled to (`DEFENCE_ALWAYS`, plus `DEFENCE_AFTER_CHARGE_SHEET` once the case is charge-sheeted) -
               never the internal investigation record.
A share may carry an expiry; an expired share counts for nothing (`share_active`).
"Court-visible": an FIR or charge sheet awaiting (or refused) its station head's approval is hidden from the court
side - judge, prosecutor, defence - until it is approved (`court_visible`).
Editing (see `can_edit_case` / `can_edit_document`): case details by officers with access and the station admin;
a document only by the department that filed it; nothing once the case is closed. Every edit is recorded (edits.py).
Requests for a case/document a user may not access get a 404, and the attempt is written to the audit log.
"""
from __future__ import annotations

from fastapi import HTTPException, Request
from sqlalchemy import and_, exists, false, or_, select, true
from sqlalchemy.orm import Session

from . import audit
from .db import utcnow
from .deps import client_ip
from .models import Case, CaseAssignment, CaseShare, Document, Station, StationOversight, User

SHARE_ROLES = ("forensic", "judge", "prosecutor", "defence")  # accounts a case can be shared with
COURT_SIDE = ("judge", "prosecutor", "defence")  # never see a document still awaiting station-head approval
OWN_UPLOADS_ONLY = ("forensic", "prosecutor", "defence")  # may edit/sign only what they filed themselves
DEFENCE_ALWAYS = ("fir", "arrest_warrant", "legal_notice", "court_filing", "judgment")
DEFENCE_AFTER_CHARGE_SHEET = ("charge_sheet", "witness_statement", "forensic_report", "medical_report", "evidence_record")
_HIDDEN_FROM_COURT = ("pending", "returned")


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


def share_active():
    """SQL condition: the `CaseShare` row has not expired."""
    return or_(CaseShare.expires_at.is_(None), CaseShare.expires_at > utcnow())


def is_shared(db: Session, user: User, case_id: int) -> bool:
    return (
        db.execute(
            select(CaseShare.id).where(CaseShare.case_id == case_id, CaseShare.shared_with_id == user.id, share_active())
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
    if user.role in ("forensic", "prosecutor", "defence"):
        return is_shared(db, user, case.id)
    return False


def court_visible(doc: Document) -> bool:
    return doc.approval_status not in _HIDDEN_FROM_COURT


def _defence_types(case: Case) -> tuple[str, ...]:
    return DEFENCE_ALWAYS if case.stage == "under_investigation" else DEFENCE_ALWAYS + DEFENCE_AFTER_CHARGE_SHEET


def can_read_document(db: Session, user: User, case: Case, doc: Document) -> bool:
    """Document-level gate, on top of `can_read_content`."""
    if not can_read_content(db, user, case):
        return False
    if user.role == "forensic":
        return doc.created_by == user.id  # never an officer's existing investigation files
    if user.role == "defence":
        return doc.created_by == user.id or (court_visible(doc) and doc.doc_type in _defence_types(case))
    if user.role in ("judge", "prosecutor"):
        return doc.created_by == user.id or court_visible(doc)
    return True


def document_scope(user: User):
    """SQL twin of the per-document part of `can_read_document`, for queries that already apply `content_scope`
    (joined to `Case` and `Document`). Must stay equivalent to it; test_workflow.py checks the two agree."""
    own = Document.created_by == user.id
    visible = Document.approval_status.notin_(_HIDDEN_FROM_COURT)
    if user.role == "forensic":
        return own
    if user.role == "defence":
        allowed = or_(
            Document.doc_type.in_(DEFENCE_ALWAYS),
            and_(Case.stage != "under_investigation", Document.doc_type.in_(DEFENCE_AFTER_CHARGE_SHEET)),
        )
        return or_(own, and_(visible, allowed))
    if user.role in ("judge", "prosecutor"):
        return or_(own, visible)
    return true()


def can_edit_case(db: Session, user: User, case: Case) -> bool:
    """Who may change a case's details: an officer with access to it, or its station's admin - and only while it
    is open. Once a verdict closes the case its record is frozen."""
    if case.status != "open":
        return False
    if user.role == "officer":
        return can_read_content(db, user, case)
    return user.role == "admin" and user.station_id is not None and user.station_id == case.station_id


def can_edit_document(db: Session, user: User, case: Case, doc: Document) -> bool:
    """Who may change a document (its title/description, or file a new version of it): only the department that
    filed it. A forensic lab's findings (or a prosecutor's / defence lawyer's filing) are edited by that account
    alone - never by the police - an officer's files by officers with access to the case, and a judge's verdict by
    nobody. Callers must already have established that the user can read the document, and check separately that
    the case is still open."""
    owner = db.get(User, doc.created_by)
    if owner is None or owner.role == "judge":
        return False
    if owner.role in OWN_UPLOADS_ONLY:
        return user.id == owner.id
    return user.role == "officer" and can_read_content(db, user, case)


def can_sign_document(db: Session, user: User, case: Case, doc: Document) -> bool:
    """Who may put their signature on a document: people of the department that filed it - officers with access to
    the case on police documents (so a station head can countersign), and otherwise only the account that filed it
    (the lab on its report, the judge on the verdict)."""
    owner = db.get(User, doc.created_by)
    if owner is None:
        return False
    if owner.role == "officer":
        return user.role == "officer" and can_read_content(db, user, case)
    return user.id == owner.id


def can_approve(db: Session, user: User, case: Case) -> bool:
    """Who decides on a document awaiting approval: the station head of the case's station, or a superintendent
    overseeing it."""
    if user.role != "officer":
        return False
    if user.rank == "station_head":
        return user.station_id is not None and user.station_id == case.station_id
    return user.rank == "superintendent" and oversees(db, user, case.station_id)


def station_has_head(db: Session, station_id: int) -> bool:
    return db.execute(
        select(User.id).where(User.role == "officer", User.rank == "station_head", User.station_id == station_id, User.is_active).limit(1)
    ).first() is not None


def can_view_case(db: Session, user: User, case: Case) -> bool:
    if user.role in ("officer",) + SHARE_ROLES:
        return can_read_content(db, user, case)  # for these roles, "view" and "content" are the same threshold
    if user.role == "admin":
        return user.station_id is not None and user.station_id == case.station_id
    return False


def content_scope(user: User):
    """A SQLAlchemy boolean expression, true for a `Case` row the user has content (case-level) access to. For
    use in list/search queries already selecting from (or joined to) `Case` - e.g. `.where(content_scope(user))`.
    Must stay logically equivalent to `can_read_content` above; `test_permissions.py` checks the two agree."""
    shared = exists().where(CaseShare.case_id == Case.id, CaseShare.shared_with_id == user.id, share_active())
    if user.role == "officer":
        conditions = [exists().where(CaseAssignment.case_id == Case.id, CaseAssignment.user_id == user.id)]
        if user.rank == "station_head" and user.station_id is not None:
            conditions.append(Case.station_id == user.station_id)
        elif user.rank == "superintendent":
            conditions.append(exists().where(StationOversight.user_id == user.id, StationOversight.station_id == Case.station_id))
        return or_(*conditions)
    if user.role == "judge":
        conditions = [shared]
        if user.rank == "high_court":
            conditions.append(true())
        elif user.rank == "district_court" and user.district_id is not None:
            conditions.append(
                exists().where(Station.id == Case.station_id, Station.district_id == user.district_id)
            )
        return or_(*conditions)
    if user.role in ("forensic", "prosecutor", "defence"):
        return shared
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
