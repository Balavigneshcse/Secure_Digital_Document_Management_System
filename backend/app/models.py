from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base, utcnow

ROLES = ("officer", "admin", "auditor", "forensic", "judge", "prosecutor", "defence")
# Meaningful only for role="officer" or role="judge"; ignored (stored as "officer") for every other role.
#   officer:  "officer" (default, assigned cases only) < "station_head" (+ every case at their own station)
#             < "superintendent" (+ every case at every station in `station_oversight`)
#   judge:    "officer" (default: old-style per-case share only, no automatic court reach)
#             < "district_court" (every case at every station in their own district)
#             < "high_court" (every case, every district)
#   admin:    "officer" (default: a station's admin) < "system" (no station: manages accounts of every role)
RANKS = ("officer", "station_head", "superintendent", "district_court", "high_court", "system")

# Where a case stands. `status` stays the coarse open/closed switch (closed = a verdict froze the record).
CASE_STAGES = ("under_investigation", "charge_sheeted", "in_trial", "judgment_delivered")
# Documents that a plain officer files and the station head must approve before the court side can see them.
APPROVAL_TYPES = ("fir", "charge_sheet")
APPROVAL_STATES = ("not_required", "pending", "approved", "returned")

DOC_TYPES = (
    "fir",
    "police_report",
    "investigation_record",
    "witness_statement",
    "charge_sheet",
    "court_filing",
    "evidence_record",
    "forensic_report",
    "legal_notice",
    "judgment",
    "medical_report",
    "arrest_warrant",
    "other",
)


class SystemMeta(Base):
    """Small key/value store for deployment-wide facts (e.g. this audit chain's id)."""

    __tablename__ = "system_meta"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(255))


class District(Base):
    """A police/judicial district: groups stations, has one forensic lab and one district court.
    Optional - a Station or User with no district is unaffected by any district-scoped rule."""

    __tablename__ = "districts"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(16), unique=True)
    name: Mapped[str] = mapped_column(String(120))


class Station(Base):
    __tablename__ = "stations"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(16), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    district_id: Mapped[int | None] = mapped_column(ForeignKey("districts.id"), nullable=True)

    district: Mapped[District | None] = relationship()


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16))
    rank: Mapped[str] = mapped_column(String(16), default="officer")  # see RANKS; only meaningful for role officer/judge
    station_id: Mapped[int | None] = mapped_column(ForeignKey("stations.id"), nullable=True)
    # The forensic lab's, or a district_court judge's, home district. Unused for every other role/rank.
    district_id: Mapped[int | None] = mapped_column(ForeignKey("districts.id"), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)

    totp_secret_enc: Mapped[str | None] = mapped_column(String(255), nullable=True)
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    totp_last_step: Mapped[int] = mapped_column(Integer, default=0)

    failed_attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[str | None] = mapped_column(String(32), nullable=True)
    token_version: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[str] = mapped_column(String(32), default=utcnow)

    station: Mapped[Station | None] = relationship()
    district: Mapped[District | None] = relationship()


class StationOversight(Base):
    """Which stations a `rank="superintendent"` officer has station-wide content access to (many-to-many)."""

    __tablename__ = "station_oversight"
    __table_args__ = (UniqueConstraint("user_id", "station_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    station_id: Mapped[int] = mapped_column(ForeignKey("stations.id"), index=True)
    granted_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    granted_at: Mapped[str] = mapped_column(String(32), default=utcnow)


class Case(Base):
    __tablename__ = "cases"
    id: Mapped[int] = mapped_column(primary_key=True)
    case_number: Mapped[str] = mapped_column(String(48), unique=True, index=True)
    fir_number: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(200))
    case_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="open")
    stage: Mapped[str] = mapped_column(String(24), default="under_investigation")  # see CASE_STAGES
    station_id: Mapped[int] = mapped_column(ForeignKey("stations.id"))
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[str] = mapped_column(String(32), default=utcnow)

    station: Mapped[Station] = relationship()
    parties: Mapped[list[CaseParty]] = relationship(cascade="all, delete-orphan")
    assignments: Mapped[list[CaseAssignment]] = relationship(cascade="all, delete-orphan")
    shares: Mapped[list[CaseShare]] = relationship(cascade="all, delete-orphan")


class CaseParty(Base):
    __tablename__ = "case_parties"
    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id"), index=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    role: Mapped[str] = mapped_column(String(32))  # complainant, accused, witness, victim, other


class CaseAssignment(Base):
    __tablename__ = "case_assignments"
    __table_args__ = (UniqueConstraint("case_id", "user_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    assigned_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    assigned_at: Mapped[str] = mapped_column(String(32), default=utcnow)

    user: Mapped[User] = relationship(foreign_keys=[user_id])


class CaseShare(Base):
    """Grants one forensic / judge / prosecutor / defence account access to one case, optionally until `expires_at`
    (after which it counts for nothing - see permissions.share_active)."""

    __tablename__ = "case_shares"
    __table_args__ = (UniqueConstraint("case_id", "shared_with_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id"), index=True)
    shared_with_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    shared_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[str] = mapped_column(String(32), default=utcnow)
    expires_at: Mapped[str | None] = mapped_column(String(32), nullable=True)  # None = until revoked

    shared_with: Mapped[User] = relationship(foreign_keys=[shared_with_id])
    granter: Mapped[User] = relationship(foreign_keys=[shared_by])


class Document(Base):
    __tablename__ = "documents"
    id: Mapped[int] = mapped_column(primary_key=True)
    # Globally unique and never reused (serial ids restart after a restore/migration; the ledger must not care).
    uid: Mapped[str] = mapped_column(String(32), unique=True, default=lambda: uuid.uuid4().hex)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    doc_type: Mapped[str] = mapped_column(String(32))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[str] = mapped_column(String(32), default=utcnow)
    current_version: Mapped[int] = mapped_column(Integer, default=1)
    # Station-head approval (see APPROVAL_TYPES). "pending"/"returned" documents are invisible to the court side.
    approval_status: Mapped[str] = mapped_column(String(16), default="not_required")
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)  # who decided (approve or return)
    approved_at: Mapped[str | None] = mapped_column(String(32), nullable=True)
    approval_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    approved_version: Mapped[int | None] = mapped_column(Integer, nullable=True)  # the version that was approved

    case: Mapped[Case] = relationship()
    creator: Mapped[User] = relationship(foreign_keys=[created_by])
    approver: Mapped[User | None] = relationship(foreign_keys=[approved_by])
    versions: Mapped[list[DocumentVersion]] = relationship(
        order_by="DocumentVersion.version_no", cascade="all, delete-orphan"
    )


class DocumentVersion(Base):
    __tablename__ = "document_versions"
    __table_args__ = (UniqueConstraint("document_id", "version_no"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), index=True)
    version_no: Mapped[int] = mapped_column(Integer)
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(100))
    size: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    storage_key: Mapped[str] = mapped_column(String(64), unique=True)
    wrapped_dek: Mapped[str] = mapped_column(String(255))
    uploaded_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    uploaded_at: Mapped[str] = mapped_column(String(32), default=utcnow, index=True)
    change_note: Mapped[str | None] = mapped_column(String(255), nullable=True)

    ledger_tx_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ledger_block: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # AI suggestion (headline only). OCR text, entities, summary, tags and embeddings live in MongoDB
    # (app/docstore.py), encrypted where they carry case content.
    ai_doc_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    ai_confidence: Mapped[float | None] = mapped_column(nullable=True)
    ai_provider: Mapped[str | None] = mapped_column(String(64), nullable=True)

    uploader: Mapped[User] = relationship(foreign_keys=[uploaded_by])


class SigningKey(Base):
    """A user's Ed25519 signing key pair. The private key is sealed with the master key (server-held - this is not a
    personal smart card or Aadhaar eSign); the public key is also anchored on the ledger when it is created, so
    swapping it in this table later is detectable."""

    __tablename__ = "signing_keys"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    public_key: Mapped[str] = mapped_column(String(64))  # base64 of the 32 raw bytes
    private_key_enc: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[str] = mapped_column(String(32), default=utcnow)
    ledger_tx_id: Mapped[str | None] = mapped_column(String(64), nullable=True)


class Signature(Base):
    """One person's signature over one document version: Ed25519 over `statement` (canonical JSON naming the
    document, version, its SHA-256, the signer and the time)."""

    __tablename__ = "signatures"
    __table_args__ = (UniqueConstraint("document_id", "version_no", "signer_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), index=True)
    version_no: Mapped[int] = mapped_column(Integer)
    signer_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    signed_at: Mapped[str] = mapped_column(String(32))
    statement: Mapped[str] = mapped_column(Text)
    signature: Mapped[str] = mapped_column(String(128))  # base64
    public_key: Mapped[str] = mapped_column(String(64))  # the signer's key at signing time

    signer: Mapped[User] = relationship(foreign_keys=[signer_id])


class AlertRead(Base):
    """How far each user has read their alerts (the id of the newest audit entry they have seen)."""

    __tablename__ = "alert_reads"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    last_seen_audit_id: Mapped[int] = mapped_column(Integer, default=0)


class EditRecord(Base):
    """What an edit changed (old and new values), for the people allowed to see the case. That it happened, when and
    by whom lives in the hash-chained audit log, whose entry carries `record_hash` - so altering or deleting a row
    here is detectable (app/edits.py). The values stay out of the audit log because auditors may not read case data."""

    __tablename__ = "edit_history"
    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id"), index=True)
    document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id"), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(16))  # case | document | version | approval
    edited_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    edited_at: Mapped[str] = mapped_column(String(32))
    reason: Mapped[str] = mapped_column(String(500))
    changes: Mapped[str] = mapped_column(Text)  # canonical JSON: [{"field", "old", "new"}, ...]
    record_hash: Mapped[str] = mapped_column(String(64))
    audit_id: Mapped[int | None] = mapped_column(Integer, nullable=True, unique=True)

    editor: Mapped[User] = relationship(foreign_keys=[edited_by])


class AuditLog(Base):
    """Append-only, hash-chained. entry_hash = SHA-256(prev_hash || canonical(fields))."""

    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[str] = mapped_column(String(32), index=True)
    actor_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    actor_username: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    actor_role: Mapped[str | None] = mapped_column(String(16), nullable=True)
    action: Mapped[str] = mapped_column(String(48), index=True)
    outcome: Mapped[str] = mapped_column(String(16))  # success | failure | denied | alert
    resource_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    resource_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    case_number: Mapped[str | None] = mapped_column(String(48), nullable=True, index=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    detail: Mapped[str] = mapped_column(Text, default="{}")  # canonical JSON
    prev_hash: Mapped[str] = mapped_column(String(64))
    entry_hash: Mapped[str] = mapped_column(String(64), unique=True)
