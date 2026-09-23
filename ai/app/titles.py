"""Explicit document titles as a prior for the classifier.

Legal documents usually announce what they are in their header ("FIRST INFORMATION REPORT", "WARRANT OF ARREST").
The fine-tuned model can be fooled by layout, so a title found in the *header zone* (the first ~240 characters)
adds a bonus to that class's score. It is a soft prior, not an override: strong contrary evidence can still win, and
any disagreement between the title and the model flags the document for human review.
"""
from __future__ import annotations

import re

HEADER_CHARS = 240

TITLES: dict[str, tuple[str, ...]] = {
    "fir": ("first information report", "f.i.r.", "प्रथम सूचना रिपोर्ट", "முதல் தகவல் அறிக்கை"),
    "charge_sheet": ("charge sheet", "chargesheet", "charge-sheet", "आरोप पत्र", "குற்றப்பத்திரிகை"),
    "arrest_warrant": ("warrant of arrest", "non-bailable warrant", "bailable warrant", "arrest warrant", "गिरफ्तारी वारंट", "கைது ஆணை"),
    "witness_statement": ("statement of witness", "witness statement", "deposition of pw", "statement under section 161",
                          "statement under section 164", "गवाह का बयान", "சாட்சியின் வாக்குமூலம்"),
    "forensic_report": ("forensic science laboratory", "fingerprint bureau", "ballistics expert", "digital forensics examination",
                        "न्यायालयिक विज्ञान प्रयोगशाला", "தடய அறிவியல் ஆய்வகம்"),
    "medical_report": ("medico-legal certificate", "medico legal certificate", "post-mortem examination report",
                       "postmortem examination report", "injury report", "चिकित्सा-विधिक प्रमाण पत्र", "மருத்துவ-சட்ட சான்றிதழ்"),
    "evidence_record": ("seizure memo", "chain of custody form", "malkhana", "list of exhibits", "जब्ती मेमो", "பறிமுதல் பட்டியல்"),
    "legal_notice": ("legal notice", "notice under section", "विधिक नोटिस", "சட்ட அறிவிப்பு"),
    "judgment": ("judgment", "order sheet", "order on charge", "निर्णय", "தீர்ப்பு"),
    "court_filing": ("bail application", "writ petition", "affidavit", "memo of parties", "जमानत प्रार्थना पत्र", "ஜாமீன் மனு"),
    "investigation_record": ("case diary", "panchnama", "spot inspection", "investigation progress report", "केस डायरी", "வழக்கு நாட்குறிப்பு"),
    "police_report": ("general diary", "daily diary", "beat officer", "police report", "सामान्य डायरी", "பொது நாட்குறிப்பு"),
}


def title_class(text: str) -> str | None:
    """The one class whose title appears in the header zone, or None if there is none or it is ambiguous."""
    head = re.sub(r"\s+", " ", (text or "")[:HEADER_CHARS * 2]).casefold()[:HEADER_CHARS]
    hits = {cls for cls, phrases in TITLES.items() if any(p in head for p in phrases)}
    return next(iter(hits)) if len(hits) == 1 else None
