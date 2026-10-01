from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


def utcnow() -> str:
    """UTC timestamp as a fixed-width ISO string (sorts lexicographically, hashes stably)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def utcnow_plus(minutes: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def make_engine(url: str) -> Engine:
    return create_engine(url, pool_pre_ping=True, pool_size=10, max_overflow=20)


def make_session_factory(engine: Engine) -> sessionmaker:
    return sessionmaker(bind=engine, expire_on_commit=False, autoflush=True)


# Columns added to tables that already existed when a feature landed. `create_all()` only creates missing *tables*,
# so these are applied (idempotently) at every start instead of asking the operator to run ALTER TABLE by hand.
_ADDED_COLUMNS = (
    "ALTER TABLE cases ADD COLUMN IF NOT EXISTS stage VARCHAR(24) NOT NULL DEFAULT 'under_investigation'",
    "ALTER TABLE case_shares ADD COLUMN IF NOT EXISTS expires_at VARCHAR(32)",
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS approval_status VARCHAR(16) NOT NULL DEFAULT 'not_required'",
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS approved_by INTEGER REFERENCES users(id)",
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS approved_at VARCHAR(32)",
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS approval_note VARCHAR(500)",
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS approved_version INTEGER",
    # cases closed by a verdict before stages existed
    "UPDATE cases SET stage = 'judgment_delivered' WHERE status = 'closed' AND stage = 'under_investigation'",
)


def ensure_columns(engine: Engine) -> None:
    with engine.begin() as c:
        c.execute(text("SELECT pg_advisory_xact_lock(hashtextextended('sdms-schema', 0))"))  # two starting workers
        for stmt in _ADDED_COLUMNS:
            c.execute(text(stmt))


def advisory_xact_lock(db: Session, name: str) -> None:
    """Takes a PostgreSQL transaction-scoped advisory lock keyed by `name`; released at commit/rollback.

    Used to serialise things that must be sequential across concurrent requests (the audit hash chain,
    case-number allocation) without serialising the whole database.
    """
    db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:n, 0))"), {"n": name})
