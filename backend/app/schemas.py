from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .models import DOC_TYPES

PartyRole = Literal["complainant", "accused", "witness", "victim", "other"]


# --- auth ---------------------------------------------------------------------------------------
class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class StageTokenOut(BaseModel):
    stage: Literal["mfa_required", "mfa_setup_required", "authenticated"]
    token: str
    must_change_password: bool = False


class CodeIn(BaseModel):
    code: str = Field(min_length=6, max_length=6)


class MfaSetupOut(BaseModel):
    secret: str
    otpauth_uri: str


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str = Field(max_length=256)


# --- users --------------------------------------------------------------------------------------
class UserOut(BaseModel):
    id: int
    username: str
    full_name: str
    role: str
    rank: str = "officer"  # only meaningful when role in (officer, judge); see app/models.py RANKS
    station_id: int | None
    station_name: str | None = None
    district_id: int | None = None  # forensic labs, and rank=district_court judges: their home district
    district_name: str | None = None
    is_active: bool
    totp_enabled: bool
    must_change_password: bool


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[a-zA-Z0-9._-]+$")
    full_name: str = Field(min_length=1, max_length=120)
    password: str = Field(max_length=256)
    role: Literal["officer"] = "officer"


class UserPatch(BaseModel):
    is_active: bool
    rank: Literal["officer", "station_head"] = "officer"  # a station admin may promote/demote within their own
    # station only; "superintendent" (multi-station) and every judge rank are granted only via the operator CLI


# --- cases --------------------------------------------------------------------------------------
class PartyIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    role: PartyRole = "other"


class CaseCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    fir_number: str | None = Field(default=None, max_length=64)
    case_type: str | None = Field(default=None, max_length=64)
    description: str | None = Field(default=None, max_length=4000)
    parties: list[PartyIn] = Field(default_factory=list, max_length=50)
    officer_ids: list[int] = Field(default_factory=list, max_length=20)  # admin-created cases only


class AssignIn(BaseModel):
    user_id: int


class ShareIn(BaseModel):
    user_id: int  # must be an active user with role "forensic" or "judge"


class ShareOut(BaseModel):
    user_id: int
    username: str
    full_name: str
    role: str
    shared_by: str
    created_at: str


class PartyOut(BaseModel):
    name: str
    role: str


class AssigneeOut(BaseModel):
    user_id: int
    username: str
    full_name: str


class CaseOut(BaseModel):
    id: int
    case_number: str
    fir_number: str | None
    title: str
    case_type: str | None
    description: str | None
    status: str
    station_id: int
    created_at: str
    parties: list[PartyOut] = []
    assignees: list[AssigneeOut] = []
    shares: list[ShareOut] = []  # forensic/judge accounts granted read-only access; visible to officer and admin
    document_count: int | None = None  # None when the viewer has no content rights


# --- documents ----------------------------------------------------------------------------------
class VersionOut(BaseModel):
    version_no: int
    filename: str
    content_type: str
    size: int
    sha256: str
    uploaded_by: str
    uploaded_at: str
    change_note: str | None
    ledger_tx_id: str | None
    ledger_block: int | None
    ai_doc_type: str | None
    ai_confidence: float | None
    ai_tags: list[str] = []
    ai_entities: dict[str, list[str]] = {}
    ai_provider: str | None
    language: str | None = None
    ocr_confidence: float | None = None
    ocr_method: str | None = None
    needs_review: bool = False
    summary: str | None = None


class DocumentOut(BaseModel):
    id: int
    uid: str
    case_id: int
    case_number: str
    title: str
    doc_type: str
    description: str | None
    created_at: str
    current_version: int
    versions: list[VersionOut] = []


class VerifyOut(BaseModel):
    document_id: int
    version_no: int
    status: Literal["verified", "tampered"]
    reasons: list[str]
    stored_sha256: str
    recomputed_sha256: str | None
    ledger_sha256: str | None
    ledger_tx_id: str | None
    ledger_block: int | None


def valid_doc_type(v: str) -> str:
    if v != "auto" and v not in DOC_TYPES:
        raise ValueError(f"doc_type must be 'auto' or one of {', '.join(DOC_TYPES)}")
    return v
