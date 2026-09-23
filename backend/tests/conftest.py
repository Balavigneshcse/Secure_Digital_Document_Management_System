from __future__ import annotations

import time
import uuid

import pyotp
import pytest
from fastapi.testclient import TestClient
from pymongo import MongoClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url

from app import security
from app.config import Settings
from app.main import create_app
from app.models import Station, StationOversight, User
from app.seed import create_user, get_or_create_district, get_or_create_station

PASSWORD = "Str0ng-Passw0rd!"

FIR_TEXT = b"""FIRST INFORMATION REPORT
FIR No. 0142/2026  Police Station Kotwali
Date of report: 12/03/2026
Complainant: Mr. Ramesh Kumar, resident of Sector Nine, reports theft.
Accused: Mr. Suresh Verma. Offence under Section 379 IPC and Section 34 IPC.
"""


class Clock:
    """Controllable time source for TOTP so several logins can happen inside one test."""

    def __init__(self):
        self.t = time.time()

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: int = 30):
        self.t += seconds


@pytest.fixture(scope="session")
def base_settings() -> Settings:
    """Connection details come from backend/.env (or SDMS_* env vars)."""
    return Settings()


@pytest.fixture
def settings_factory(base_settings, tmp_path):
    """Builds Settings pointing at a brand-new PostgreSQL database + MongoDB database, dropped afterwards."""
    made: list[tuple[str, str]] = []
    admin_url = make_url(base_settings.database_url).set(database="postgres")
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")

    def make(**over) -> Settings:
        name = f"sdms_t_{uuid.uuid4().hex[:12]}"
        with admin.connect() as c:
            c.execute(text(f'CREATE DATABASE "{name}"'))
        made.append((name, name))
        kw = dict(
            database_url=make_url(base_settings.database_url).set(database=name).render_as_string(hide_password=False),
            mongo_url=base_settings.mongo_url, mongo_db=name, ledger_backend="memory",
            data_dir=tmp_path, audit_anchor_interval_seconds=0,
            # Hermetic: a developer's backend/.env (real AI service, gateway...) must never leak into unit tests.
            ai_service_url=None, ai_service_key=None,
            rate_limit_enabled=False,  # exercised explicitly in test_security.py; tests share one client address
        )
        kw.update(over)
        return Settings(**kw)

    yield make

    mongo = MongoClient(base_settings.mongo_url, serverSelectionTimeoutMS=5000)
    for pg_name, mongo_name in made:
        with admin.connect() as c:
            c.execute(text(f'DROP DATABASE IF EXISTS "{pg_name}" WITH (FORCE)'))
        mongo.drop_database(mongo_name)
    mongo.close()
    admin.dispose()


class World:
    def __init__(self, app, client: TestClient, clock: Clock):
        self.app, self.client, self.clock = app, client, clock
        self.secrets: dict[str, str] = {}
        self._headers: dict[str, dict] = {}

    # -- setup helpers -------------------------------------------------------------------------
    def add_user(self, username: str, role: str, station: str | None = "CPS", rank: str = "officer",
                district: str | None = None, must_change: bool = False):
        no_station = role in ("auditor", "forensic", "judge") or (role == "officer" and rank == "superintendent")
        with self.app.state.session_factory() as db:
            d = get_or_create_district(db, district, f"{district} District") if district else None
            st = None if (station is None or no_station) else get_or_create_station(db, station, f"{station} Police Station", d)
            create_user(db, username=username, full_name=username.title(), password=PASSWORD, role=role, rank=rank,
                        station=st, district=d, must_change_password=must_change)
            db.commit()

    def user_row(self, db, username: str) -> User:
        return db.execute(select(User).where(User.username == username)).scalar_one()

    def _uid(self, username: str) -> int:
        with self.app.state.session_factory() as db:
            return self.user_row(db, username).id

    def oversee(self, username: str, station: str):
        """Grants a rank=superintendent user content access to an extra station (bypasses the API - test setup only)."""
        with self.app.state.session_factory() as db:
            u = db.execute(select(User).where(User.username == username)).scalar_one()
            st = get_or_create_station(db, station, f"{station} Police Station")
            db.add(StationOversight(user_id=u.id, station_id=st.id, granted_by=u.id))
            db.commit()

    def station_district(self, station_code: str, district_code: str):
        """Links an already-existing station to a district (test setup only)."""
        with self.app.state.session_factory() as db:
            st = db.execute(select(Station).where(Station.code == station_code)).scalar_one()
            d = get_or_create_district(db, district_code, f"{district_code} District")
            st.district_id = d.id
            db.commit()

    def code(self, username: str) -> str:
        self.clock.advance(30)
        return pyotp.TOTP(self.secrets[username]).generate_otp(int(self.clock() // 30))

    def login(self, username: str, password: str = PASSWORD) -> dict:
        """Full password + TOTP login (enrolling MFA on first use). Returns auth headers."""
        r = self.client.post("/api/auth/login", json={"username": username, "password": password})
        assert r.status_code == 200, r.text
        j = r.json()
        h = {"Authorization": f"Bearer {j['token']}"}
        if j["stage"] == "mfa_setup_required":
            self.secrets[username] = self.client.post("/api/auth/mfa/setup", headers=h).json()["secret"]
            r = self.client.post("/api/auth/mfa/enable", headers=h, json={"code": self.code(username)})
        else:
            r = self.client.post("/api/auth/mfa/verify", headers=h, json={"code": self.code(username)})
        assert r.status_code == 200, r.text
        self._headers[username] = {"Authorization": f"Bearer {r.json()['token']}"}
        return self._headers[username]

    def h(self, username: str) -> dict:
        return self._headers.get(username) or self.login(username)

    # -- domain helpers ------------------------------------------------------------------------
    def make_case(self, username: str = "officer1", **over) -> dict:
        body = {"title": "Theft at market", "fir_number": "FIR-142/2026", "case_type": "theft",
                "parties": [{"name": "Ramesh Kumar", "role": "complainant"}]}
        body.update(over)
        r = self.client.post("/api/cases", headers=self.h(username), json=body)
        assert r.status_code == 201, r.text
        return r.json()

    def upload(self, case_id: int, username: str = "officer1", data: bytes = FIR_TEXT, name: str = "fir.txt",
               title: str = "FIR 142", doc_type: str = "auto", expect: int = 201):
        r = self.client.post(
            f"/api/cases/{case_id}/documents", headers=self.h(username),
            data={"title": title, "doc_type": doc_type}, files={"file": (name, data, "application/octet-stream")},
        )
        assert r.status_code == expect, r.text
        return r.json()

    def audit_actions(self, **params) -> list[dict]:
        r = self.client.get("/api/audit", headers=self.h("auditor1"), params={"limit": 200, **params})
        assert r.status_code == 200, r.text
        return r.json()["items"]


@pytest.fixture
def clock(monkeypatch):
    c = Clock()
    monkeypatch.setattr(security, "_time", c)
    return c


@pytest.fixture
def app(settings_factory, clock):
    return create_app(settings_factory())


@pytest.fixture
def world(app, clock):
    with TestClient(app) as client:
        w = World(app, client, clock)
        w.add_user("admin1", "admin")
        w.add_user("officer1", "officer")
        w.add_user("officer2", "officer")
        w.add_user("auditor1", "auditor")
        yield w
