"""Hallucination guard for LLM-written text.

Small local models invent details - a section of law, a date, an amount - that read plausibly but are not in the document.
In a legal records system that is unacceptable, and telling the model not to is not enough. This module checks every
*checkable* fact in the generated text (sections of law, dates, amounts, phone numbers, vehicle plates, case numbers)
against the source document and drops any sentence that contains one the source does not contain.

It cannot catch a wrong claim that has no structured fact in it (e.g. "the accused was violent"), so summaries are still
labelled AI-written in the UI. What it guarantees: no fabricated section number, date, amount or identifier survives.
"""
from __future__ import annotations

import re

from . import entities

_SENT = re.compile(r"(?<=[.!?।])\s+")


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.translate(entities._DIGITS)).casefold()


def _has_number(num: str, source: str) -> bool:
    """`num` appears in the source as a standalone number (leading zeros ignored: 04 == 4)."""
    n = num.lstrip("0") or "0"
    return re.search(rf"(?<![\d])0*{re.escape(n)}(?![\d])", source) is not None


def unsupported(text: str, source: str) -> list[str]:
    """Checkable facts in `text` that do not occur in `source`."""
    src = _norm(source)
    src_nocomma = src.replace(",", "")
    e = entities.extract(text)
    bad: list[str] = []
    for sec in e["sections"]:
        m = re.match(r"\d+", sec)
        if m and not _has_number(m.group(0), src):
            bad.append(f"section {sec}")
    for d in e["dates"]:  # models reformat dates ("2 April 2026"), so compare the numbers, not the string
        if any(not _has_number(n, src) for n in re.findall(r"\d+", d)):
            bad.append(f"date {d}")
    for a in e["amounts"]:
        digits = re.sub(r"[^\d.]", "", re.sub(r"^\D+", "", a)).rstrip(".")   # the number only - not the "Rs." prefix
        if digits and digits not in src_nocomma:
            bad.append(f"amount {a}")
    for key in ("phones", "vehicles", "case_numbers"):
        for v in e[key]:
            if _norm(v) not in src and re.sub(r"[\s-]", "", _norm(v)) not in re.sub(r"[\s-]", "", src):
                bad.append(f"{key[:-1]} {v}")
    return bad


def ground(text: str, source: str) -> tuple[str, list[str]]:
    """Returns (text without any sentence that states an unsupported fact, the facts that were removed)."""
    kept, removed = [], []
    for sentence in _SENT.split(text.strip()):
        bad = unsupported(sentence, source)
        if bad:
            removed.extend(bad)
        elif sentence.strip():
            kept.append(sentence.strip())
    return " ".join(kept), removed
