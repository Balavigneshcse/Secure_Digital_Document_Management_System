"""Document-type classifier: the fine-tuned transformer (see training/), with a keyword fallback."""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path

import numpy as np

log = logging.getLogger("sentinel.classifier")

LABELS = [
    "fir", "police_report", "investigation_record", "witness_statement", "charge_sheet", "court_filing",
    "evidence_record", "forensic_report", "legal_notice", "judgment", "medical_report", "arrest_warrant", "other",
]
REVIEW_BELOW = float(os.getenv("CLASSIFIER_REVIEW_BELOW", "0.6"))

_RULES = {
    "fir": ("first information report", "fir no", "f.i.r", "प्रथम सूचना", "முதல் தகவல்"),
    "charge_sheet": ("charge sheet", "chargesheet", "final report", "आरोप पत्र", "குற்றப்பத்திரிகை"),
    "witness_statement": ("statement of witness", "section 161", "section 164", "deposition", "गवाह का बयान", "வாக்குமூலம்"),
    "forensic_report": ("forensic", "fsl", "dna", "fingerprint", "ballistic", "प्रयोगशाला", "தடய"),
    "court_filing": ("bail application", "petition", "before the hon'ble", "affidavit", "जमानत", "ஜாமீன்"),
    "judgment": ("judgment", "convicted", "acquitted", "order sheet", "निर्णय", "தீர்ப்பு"),
    "legal_notice": ("legal notice", "notice under", "विधिक नोटिस", "சட்ட அறிவிப்பு"),
    "evidence_record": ("seizure memo", "chain of custody", "malkhana", "exhibit", "जब्ती", "பறிமுதல்"),
    "investigation_record": ("case diary", "panchnama", "spot inspection", "केस डायरी", "நாட்குறிப்பு"),
    "police_report": ("general diary", "daily diary", "police report", "रोजनामचा", "பொது நாட்குறிப்பு"),
    "medical_report": ("medico-legal", "mlc", "post-mortem", "injury report", "एम.एल.सी", "மருத்துவ-சட்ட"),
    "arrest_warrant": ("warrant of arrest", "non-bailable warrant", "गिरफ्तारी वारंट", "கைது ஆணை"),
}


def rules_classify(text: str) -> tuple[str, float, dict[str, float]]:
    low = text.lower()
    scores = {k: float(sum(low.count(w) for w in ws)) for k, ws in _RULES.items()}
    best, s = max(scores.items(), key=lambda kv: kv[1])
    if s == 0:
        return "other", 0.0, {}
    total = sum(scores.values())
    return best, min(0.9, 0.35 + 0.15 * s), {k: round(v / total, 3) for k, v in scores.items() if v}


class Classifier:
    """Lazy-loads the fine-tuned model from `path`; if it isn't there, falls back to keyword rules."""

    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()
        self._loaded = False
        self.model = self.tok = None
        self.temperature = 1.0
        self.max_len = 256
        # Chosen by measurement (training/evaluate.py grid, recorded in metrics.json): 8 lets an explicit title decide
        # unless the model strongly disagrees - and any disagreement is flagged for human review.
        self.title_bonus = float(os.getenv("TITLE_BONUS", "8.0"))
        self.info: dict = {"engine": "rules-fallback"}
        self.error: str | None = None
        self._failed_at = 0.0

    def _load(self) -> None:
        with self._lock:
            if self._loaded:
                return
            if self._failed_at and time.monotonic() - self._failed_at < 30:
                return  # a load just failed: use the fallback for now, retry shortly
            if not (self.path / "config.json").exists():
                log.warning("no fine-tuned classifier at %s; using keyword rules", self.path)
                self._loaded = True
                return
            try:
                import torch
                from transformers import AutoModelForSequenceClassification, AutoTokenizer

                torch.set_num_threads(max(1, min(4, os.cpu_count() or 2)))
                tok = AutoTokenizer.from_pretrained(self.path)
                model = AutoModelForSequenceClassification.from_pretrained(self.path).eval()
                cal = self.path / "calibration.json"
                temperature = float(json.loads(cal.read_text()).get("temperature", 1.0)) if cal.exists() else 1.0
                met = self.path / "metrics.json"
                m = json.loads(met.read_text()) if met.exists() else {}
            except Exception as exc:  # never fail silently and never fail permanently
                self.error, self._failed_at = f"{type(exc).__name__}: {exc}"[:200], time.monotonic()
                log.exception("classifier failed to load; using keyword rules and retrying in 30s")
                return
            self.tok, self.model, self.temperature = tok, model, temperature
            self.max_len = int(m.get("max_len", 256))
            self.error = None
            hybrid = m.get("hybrid") or {}
            self.info = {
                "engine": "sentinel-classifier", "base_model": m.get("base_model"), "temperature": temperature,
                "title_bonus": self.title_bonus,
                # measured accuracy (synthetic + independent test sets) - not the training-set score
                "measured_accuracy": {k: round(v["accuracy"], 3) for k, v in hybrid.items() if isinstance(v, dict) and "accuracy" in v},
            }
            self._loaded = True

    def status(self) -> dict:
        if self.model is not None:
            return {"state": "ready", **self.info}
        if self.error:
            return {"state": "failed", "engine": "rules-fallback", "error": self.error}
        return {"state": "fallback" if self._loaded else "loading", "engine": "rules-fallback"}

    @property
    def ready(self) -> bool:
        self._load()
        return self.model is not None

    def classify(self, text: str) -> dict:
        self._load()
        text = (text or "").strip()
        if not text:
            return {"doc_type": "other", "confidence": 0.0, "scores": {}, "engine": "none", "needs_review": True}
        if self.model is None:
            t, c, s = rules_classify(text)
            return {"doc_type": t, "confidence": c, "scores": s, "engine": "rules-fallback", "needs_review": c < REVIEW_BELOW}
        import torch

        enc = self.tok(text[:6000], truncation=True, max_length=self.max_len, return_tensors="pt")
        with torch.no_grad():
            logits = self.model(**enc).logits[0].numpy() / self.temperature
        return self._finish(text, logits)

    def _finish(self, text: str, logits: np.ndarray) -> dict:
        """Softmax + the header-title prior. Split out so evaluation can score exactly what the service returns."""
        from .titles import title_class

        before = int(np.argmax(logits))
        tc = title_class(text)
        if tc is not None and self.title_bonus:
            logits = logits.copy()
            logits[LABELS.index(tc)] += self.title_bonus
        p = np.exp(logits - logits.max())
        p /= p.sum()
        order = np.argsort(-p)
        top = int(order[0])
        # a title that contradicts the model's own first choice is a warning sign even if the final answer follows the title
        disagree = tc is not None and LABELS[before] != tc
        return {
            "doc_type": LABELS[top], "confidence": round(float(p[top]), 4),
            "scores": {LABELS[int(i)]: round(float(p[i]), 4) for i in order[:5]},
            "engine": "sentinel-classifier", "needs_review": float(p[top]) < REVIEW_BELOW or disagree,
            "title_class": tc,
        }
