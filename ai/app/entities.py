"""Deterministic entity extraction for police / court documents.

Regexes handle everything with a fixed shape (sections of law, dates, FIR / case numbers, phone numbers, vehicle
plates, amounts) in English, Hindi and Tamil. People, places and organisations are inherently fuzzy - they come from
honorific/keyword patterns here and are enriched by the local LLM when it is available (see llm.py).
"""
from __future__ import annotations

import re

_DIGITS = {**{0x0966 + i: ord("0") + i for i in range(10)}, **{0x0BE6 + i: ord("0") + i for i in range(10)}}  # Devanagari, Tamil

_ACTS = (r"IPC|I\.P\.C\.?|Indian\s+Penal\s+Code|Cr\.?P\.?C\.?|Code\s+of\s+Criminal\s+Procedure|BNSS|BNS|"
         r"Bharatiya\s+Nyaya\s+Sanhita|Bharatiya\s+Nagarik\s+Suraksha\s+Sanhita|NDPS|POCSO|IT\s*Act|"
         r"Information\s+Technology\s+Act|Evidence\s+Act|Arms\s+Act|"
         r"भा\.दं\.सं\.?|दं\.प्र\.सं\.?|बीएनएस|बीएनएसएस|இ\.த\.ச|பி\.என்\.எஸ்")
# canonical act name, keyed by the act text with dots/spaces removed and upper-cased
_ACT_CANON = {
    "IPC": "IPC", "INDIANPENALCODE": "IPC", "भादंसं": "IPC", "இதச": "IPC",
    "CRPC": "CrPC", "CODEOFCRIMINALPROCEDURE": "CrPC", "दंप्रसं": "CrPC",
    "BNS": "BNS", "BHARATIYANYAYASANHITA": "BNS", "बीएनएस": "BNS", "பிஎன்எஸ்": "BNS",
    "BNSS": "BNSS", "BHARATIYANAGARIKSURAKSHASANHITA": "BNSS", "बीएनएसएस": "BNSS",
    "ITACT": "IT Act", "INFORMATIONTECHNOLOGYACT": "IT Act", "EVIDENCEACT": "Evidence Act", "ARMSACT": "Arms Act",
    "NDPS": "NDPS", "POCSO": "POCSO",
}
_NUM = r"\d+[A-Za-z]?(?:\(\d+\))?(?:\([a-z]\))?"
_NUMS = rf"{_NUM}(?:\s*(?:,|and|&|और)\s*{_NUM})*"

SECTION_PREFIXED = re.compile(rf"(?:\b(?:Sections?|Secs?\.?|S\.|u/s|U/S)|धारा|பிரிவு)\s*({_NUMS})\s*(?:of\s+(?:the\s+)?)?({_ACTS})?", re.I)
SECTION_SUFFIXED = re.compile(rf"\b({_NUMS})\s*(?:of\s+(?:the\s+)?)?({_ACTS})", re.I)
DATE = re.compile(
    r"\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{2}-\d{2}|\d{1,2}(?:st|nd|rd|th)?\s+"
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?,?\s+\d{4})\b", re.I)
CASE_NO = re.compile(r"(?:FIR|F\.I\.R\.?|Crime|Case|Cr\.?|CC|SC|MLC|GD|Lab(?:oratory)?)\s*(?:No\.?|Number|संख्या|எண்)?\s*[:.]?\s*((?:[A-Z]+/)?\d{1,5}\s*/\s*\d{2,4})", re.I)
PHONE = re.compile(r"(?<!\d)(?:\+91[\s-]?)?([6-9]\d{9})(?!\d)")
VEHICLE = re.compile(r"\b([A-Z]{2}[\s-]?\d{1,2}[\s-]?[A-Z]{1,3}[\s-]?\d{4})\b")
AMOUNT = re.compile(r"(?:Rs\.?|INR|₹)\s?([\d,]+(?:\.\d+)?)", re.I)

# Names and places use a single space between words, so a name can never run on into the next form field
# ("Kotwali   FIR No." must give "Kotwali", not "Kotwali FIR No").
_NAME = r"[A-Z][a-z]+(?: [A-Z][a-z]+){0,2}"
HONORIFIC = r"(?:Mr|Mrs|Ms|Smt|Shri|Sh|Dr|Inspector|Sub-Inspector|SI|ASI|Head Constable|Constable|Advocate|Adv)"
PERSON_EN = re.compile(rf"\b{HONORIFIC}\.?[ \t]+({_NAME})")
PERSON_REL = re.compile(rf"\b(?:S/o|D/o|W/o|C/o|son of|daughter of|wife of)[ \t]+({_NAME})")
PERSON_LABEL = re.compile(rf"\b(?:Complainant|Informant|Accused|Witness|Deceased|Victim|Applicant|Petitioner|Appellant|Name|Patient)\s*(?:\(\w+\))?[:\-][ \t]*(?:(?:Mr|Mrs|Ms|Smt|Shri|Sh)\.?[ \t]+)?([A-Z][a-z]+(?: [A-Z][a-z]+){{1,2}})")
PERSON_HI = re.compile(r"(?:श्रीमती|श्री|सुश्री|मैं)\s+((?:[ऀ-ॿ]+)(?:\s[ऀ-ॿ]+){0,2}?)(?=\s*[,।]|\s+(?:ने|को|से|का|की|के|उम्र|निवासी|आयु|पुत्र|पुत्री))")
PERSON_TA = re.compile(r"(?:நான்|திரு|திருமதி)\s+((?:[஀-௿]+)(?:\s[஀-௿]+){0,2}?)(?=\s*[,]|\s+வயது)")
LOC_EN = re.compile(rf"\b(?:P\.?S\.?|Police Station|resident of|r/o|R/o|village|District|Dist\.?)[ \t]*:?[ \t]*({_NAME})")
LOC_HI = re.compile(r"(?:थाना|जिला|निवासी|स्थान)\s*:?\s*([ऀ-ॿ]+)(?=[,\s।.]|$)")
LOC_TA = re.compile(r"(?:காவல் நிலையம்|மாவட்டம்|முகவரி)\s*:?\s*([஀-௿]+)(?=[,\s.।]|$)")

_STOP_NAMES = {"first information", "police station", "case no", "charge sheet", "witness statement", "investigating officer"}

# section number -> offence tag (IPC / BNS), used to give documents searchable topic tags
OFFENCE_TAGS = {
    "302": "murder", "103": "murder", "307": "attempt to murder", "109": "attempt to murder", "379": "theft", "303": "theft",
    "380": "theft", "305": "theft", "457": "house-breaking", "331": "house-breaking", "392": "robbery", "309": "robbery",
    "323": "hurt", "324": "hurt", "115": "hurt", "118": "hurt", "420": "cheating", "318": "cheating", "406": "breach of trust",
    "316": "breach of trust", "467": "forgery", "468": "forgery", "471": "forgery", "338": "forgery", "506": "criminal intimidation",
    "351": "criminal intimidation", "384": "extortion", "308": "extortion", "498A": "cruelty to wife", "85": "cruelty to wife",
    "354D": "stalking", "78": "stalking", "363": "kidnapping", "137": "kidnapping", "366": "kidnapping", "376": "sexual offence",
    "64": "sexual offence", "304A": "death by negligence", "106": "death by negligence", "304B": "dowry death", "80": "dowry death",
    "66C": "identity theft", "66D": "cheating by personation", "419": "cheating by personation", "319": "cheating by personation",
}


def _uniq(items, limit: int) -> list[str]:
    seen, out = set(), []
    for i in items:
        i = re.sub(r"\s+", " ", i).strip(" .,:;-")
        if i and i.lower() not in seen:
            seen.add(i.lower())
            out.append(i)
        if len(out) >= limit:
            break
    return out


def _sections(text: str) -> list[str]:
    found: list[tuple[str, str]] = []  # (number, canonical act or "")
    for rx in (SECTION_PREFIXED, SECTION_SUFFIXED):
        for m in rx.finditer(text):
            key = re.sub(r"[.\s]", "", m.group(2) or "").upper()
            act = _ACT_CANON.get(key) or _ACT_CANON.get(re.sub(r"[.\s]", "", m.group(2) or ""), "")
            for n in re.split(r"\s*(?:,|and|&|और)\s*", m.group(1)):
                if n and len(n) <= 10 and n[0].isdigit():
                    found.append((n, act))
    # "Section 379 ... u/s 34": a bare number inherits the act when the document names exactly one act
    acts = {a for _, a in found if a}
    only = next(iter(acts)) if len(acts) == 1 else ""
    named = {n for n, a in found if a}
    out = [f"{n} {a or only}".strip() for n, a in found if a or only or n not in named]
    return _uniq(out, 25)


def extract(text: str) -> dict[str, list[str]]:
    t = text.translate(_DIGITS)
    persons = [n for n in (PERSON_EN.findall(t) + PERSON_REL.findall(t) + PERSON_LABEL.findall(t) + PERSON_HI.findall(text) + PERSON_TA.findall(text))
               if n.strip().lower() not in _STOP_NAMES]
    return {
        "persons": _uniq(persons, 25),
        "locations": _uniq(LOC_EN.findall(t) + LOC_HI.findall(text) + LOC_TA.findall(text), 25),
        "dates": _uniq(DATE.findall(t), 25),
        "sections": _sections(t),
        "case_numbers": _uniq(CASE_NO.findall(t), 10),
        "phones": _uniq(PHONE.findall(t), 10),
        "vehicles": _uniq(VEHICLE.findall(t), 10),
        "amounts": _uniq([f"Rs. {a}" for a in AMOUNT.findall(t)], 10),
    }


def offence_tags(sections: list[str]) -> list[str]:
    out = []
    for s in sections:
        m = re.match(r"\d+[A-Za-z]?", s)
        tag = OFFENCE_TAGS.get(m.group(0)) if m else None
        if tag and tag not in out:
            out.append(tag)
    return out
