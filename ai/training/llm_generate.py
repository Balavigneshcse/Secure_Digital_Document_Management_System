"""Has the LOCAL Ollama model write documents, as (a) an independent test set - a different "author" from the
templates - and (b) extra, more diverse training data.

    python -m training.llm_generate --out data/llm_test.jsonl  --per-class 8  --seed 101
    python -m training.llm_generate --out data/llm_train.jsonl --per-class 24 --seed 202

Labels come from the prompt, not from a human, so the set contains some label noise (a 3B model sometimes drifts
into the wrong document type); results measured on it are indicative rather than exact. Resumable.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import time

import httpx

from .pools import DISTRICTS, LABELS, OFFENCES, R

DESC = {
    "fir": "a First Information Report (FIR) registered at an Indian police station",
    "police_report": "a police station record such as a general diary entry, a complaint letter addressed to the Station House Officer, a missing-person report or a beat officer's report (NOT an FIR)",
    "investigation_record": "an investigation record such as a case diary entry, a panchnama / spot inspection memo, or an investigation progress report by the investigating officer",
    "witness_statement": "a witness statement: a statement recorded by police under Section 161 CrPC, a statement before a magistrate under Section 164, or a court deposition in question-and-answer form",
    "charge_sheet": "a charge sheet / final report filed by the police under Section 173 CrPC or Section 193 BNSS",
    "court_filing": "a filing before an Indian court: a bail application, petition, affidavit, remand application or memo of parties",
    "evidence_record": "an evidence document: a seizure memo, chain-of-custody form, malkhana register entry or exhibit list",
    "forensic_report": "a forensic laboratory report (DNA, fingerprint, ballistics, digital forensics or toxicology)",
    "legal_notice": "a legal notice sent by an advocate on behalf of a client, or a statutory notice issued to a person",
    "judgment": "an Indian court judgment or order (final judgment, bail order, or order framing charges)",
    "medical_report": "a medical document: a medico-legal certificate (MLC), post-mortem report or injury report",
    "arrest_warrant": "a warrant issued by an Indian court: arrest warrant, non-bailable warrant or proclamation of an absconder",
    "other": "an ordinary non-legal document from an office or private life (office memo, invoice, personal letter, meeting minutes, bank statement, receipt, event notice)",
}
STYLES = [
    "formatted like a typed government form with numbered fields",
    "written as flowing paragraphs like an official letter",
    "as a compact half-page record using abbreviations common in Indian police and court documents",
    "with a header block and a signature block, as it would look on a scanned page",
    "in a plain narrative style without headings",
]


def make_prompt(cls: str, r: R) -> str:
    off = r.offence()
    words = r.choice([120, 160, 200, 250])
    scenario = "" if cls == "other" else f" Scenario: {off['en']} in {r.choice(DISTRICTS)}, involving fictional people; use dates in {r.choice([2023, 2024, 2025, 2026])}."
    return (f"Write realistic sample text for {DESC[cls]}. Style: {r.choice(STYLES)}.{scenario} "
            f"Length about {words} words. Output ONLY the document text - no commentary, no markdown, no explanation.")


def generate(prompt: str, model: str, url: str, temperature: float) -> str:
    r = httpx.post(f"{url}/api/generate", timeout=180, json={
        "model": model, "prompt": prompt, "stream": False, "keep_alive": "10m",
        "options": {"temperature": temperature, "top_p": 0.95, "num_predict": 380, "num_ctx": 2048}})
    r.raise_for_status()
    return r.json()["response"].strip()


def acceptable(text: str) -> bool:
    if len(text.split()) < 50:
        return False
    return not re.search(r"\b(as an ai|i cannot|i can't|sure, here|here is (a|the)|certainly)\b", text[:200], re.I)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--per-class", type=int, default=8)
    ap.add_argument("--seed", type=int, default=101)
    ap.add_argument("--model", default="qwen2.5:3b")
    ap.add_argument("--url", default="http://127.0.0.1:11434")
    ap.add_argument("--temperature", type=float, default=0.9)
    args = ap.parse_args()
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    have = {}
    if out.exists():
        for line in out.read_text(encoding="utf-8").splitlines():
            have[json.loads(line)["label"]] = have.get(json.loads(line)["label"], 0) + 1
    r = R(args.seed)
    t0, made = time.time(), 0
    with open(out, "a", encoding="utf-8") as f:
        for cls in LABELS:
            need = args.per_class - have.get(cls, 0)
            attempts = 0
            while need > 0 and attempts < args.per_class * 3:
                attempts += 1
                try:
                    text = generate(make_prompt(cls, r), args.model, args.url, args.temperature)
                except (httpx.HTTPError, KeyError) as exc:
                    print("generation error:", exc)
                    time.sleep(5)
                    continue
                if acceptable(text):
                    f.write(json.dumps({"text": text, "label": cls, "lang": "en", "variant": -1, "source": "llm"}, ensure_ascii=False) + "\n")
                    f.flush()
                    need, made = need - 1, made + 1
            print(f"{cls:22s} done  ({made} docs, {time.time() - t0:.0f}s)", flush=True)


if __name__ == "__main__":
    main()
