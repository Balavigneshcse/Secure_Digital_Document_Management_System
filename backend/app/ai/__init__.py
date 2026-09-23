"""Pluggable AI layer. The rest of the system only sees the `AIClient` interface; the fixed HTTP
contract (docs/AI_CONTRACT.md) is implemented by the local AI service in /ai. When no service is
configured, a rule-based stub keeps the pipeline working (no scanned-image OCR, no embeddings)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class AIResult:
    # OCR / text extraction
    text: str = ""
    language: str | None = None
    ocr_confidence: float = 0.0
    ocr_method: str = "none"
    pages: list[int] = field(default_factory=list)
    needs_review: bool = False
    # classification
    doc_type: str = "other"
    doc_confidence: float = 0.0
    scores: dict[str, float] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    # entities: persons, locations, dates, sections, case_numbers, organizations, phones, vehicles, amounts ...
    entities: dict[str, list[str]] = field(default_factory=dict)
    # semantic-search vector (None when the provider can't embed)
    embedding: list[float] | None = None
    engine: str = "none"


class AIServiceError(Exception):
    pass


class AIClient(Protocol):
    name: str

    def process(self, filename: str, content_type: str, data: bytes) -> AIResult: ...
    def embed(self, text: str) -> list[float] | None: ...
    def summarize(self, text: str) -> str | None: ...
    def summarize_case(self, documents: list[dict]) -> dict | None: ...
