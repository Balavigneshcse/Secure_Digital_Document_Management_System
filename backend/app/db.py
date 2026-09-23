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


def advisory_xact_lock(db: Session, name: str) -> None:
    """Takes a PostgreSQL transaction-scoped advisory lock keyed by `name`; released at commit/rollback.

    Used to serialise things that must be sequential across concurrent requests (the audit hash chain,
    case-number allocation) without serialising the whole database.
    """
    db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:n, 0))"), {"n": name})
