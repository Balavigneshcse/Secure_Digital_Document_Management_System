"""Demo data (SDMS_SEED_DEMO=true). Passwords here are for local demos only."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import CaseShare, District, Station, StationOversight, User
from .security import hash_password

DEMO_PASSWORD = "Demo@Pass1234"


def get_or_create_district(db: Session, code: str, name: str) -> District:
    d = db.execute(select(District).where(District.code == code)).scalar_one_or_none()
    if d is None:
        d = District(code=code, name=name)
        db.add(d)
        db.flush()
    return d


def get_or_create_station(db: Session, code: str, name: str, district: District | None = None) -> Station:
    st = db.execute(select(Station).where(Station.code == code)).scalar_one_or_none()
    if st is None:
        st = Station(code=code, name=name, district_id=district.id if district else None)
        db.add(st)
        db.flush()
    elif district is not None and st.district_id is None:
        st.district_id = district.id  # backfill: a station created before districts existed
    return st


def create_user(db: Session, *, username: str, full_name: str, password: str, role: str,
                station: Station | None, rank: str = "officer", district: District | None = None,
                must_change_password: bool = False) -> User:
    user = User(
        username=username.lower(), full_name=full_name, password_hash=hash_password(password), role=role, rank=rank,
        station_id=station.id if station else None, district_id=district.id if district else None,
        must_change_password=must_change_password,
    )
    db.add(user)
    db.flush()
    return user


def seed_demo(db: Session) -> None:
    if db.execute(select(User.id).limit(1)).first():
        return
    cps = get_or_create_station(db, "CPS", "Central Police Station (Demo)")
    north = get_or_create_station(db, "NPS", "Northside Police Station (Demo)")

    admin = create_user(db, username="admin.demo", full_name="Station Admin (Demo)", password=DEMO_PASSWORD, role="admin", station=cps)
    officer1 = create_user(db, username="officer.demo", full_name="Insp. Officer One (Demo)", password=DEMO_PASSWORD, role="officer", station=cps)
    officer2 = create_user(db, username="officer2.demo", full_name="SI Officer Two (Demo)", password=DEMO_PASSWORD, role="officer", station=cps)
    create_user(db, username="auditor.demo", full_name="Auditor (Demo)", password=DEMO_PASSWORD, role="auditor", station=None)

    # Senior officers: same role="officer", a wider `rank`.
    sho = create_user(db, username="sho.demo", full_name="Insp. Station House Officer (Demo)", password=DEMO_PASSWORD,
                       role="officer", station=cps, rank="station_head")
    sp = create_user(db, username="sp.demo", full_name="SP Superintendent (Demo)", password=DEMO_PASSWORD,
                      role="officer", station=None, rank="superintendent")
    db.flush()
    db.add(StationOversight(user_id=sp.id, station_id=cps.id, granted_by=admin.id))
    db.add(StationOversight(user_id=sp.id, station_id=north.id, granted_by=admin.id))

    # Cross-department reviewers: no station, no case access until an officer/admin shares a specific case.
    forensic1 = create_user(db, username="forensic.demo", full_name="Forensic Analyst One (Demo)", password=DEMO_PASSWORD, role="forensic", station=None)
    create_user(db, username="forensic2.demo", full_name="Forensic Analyst Two (Demo)", password=DEMO_PASSWORD, role="forensic", station=None)
    judge = create_user(db, username="judge.demo", full_name="Judge (Demo)", password=DEMO_PASSWORD, role="judge", station=None)

    from .models import Case, CaseAssignment  # local import: keeps this module's top-level surface small

    case = Case(case_number=f"CR-{cps.code}-DEMO-0001", title="Demo case for sharing", case_type="other",
                station_id=cps.id, created_by=officer1.id)
    case.assignments = [CaseAssignment(user_id=officer1.id, assigned_by=officer1.id),
                        CaseAssignment(user_id=officer2.id, assigned_by=officer1.id)]
    case.shares = [CaseShare(shared_with_id=forensic1.id, shared_by=officer1.id),
                   CaseShare(shared_with_id=judge.id, shared_by=admin.id)]
    db.add(case)
    db.commit()
