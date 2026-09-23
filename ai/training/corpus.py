"""Builds the synthetic training corpus.

    python -m training.corpus --out data --seed 7

Splits:
  train         - every layout except the held-out ones, + Hindi + Tamil, with cross-class distractors and OCR noise
  val_seen      - fresh random documents from the training layouts (early stopping)
  val_unseen    - the HELD-OUT layout of every class: formats the model never saw (the honest generalisation check)
  val_unseen_noisy - the same held-out documents after heavy OCR-style corruption
Nothing here is real case data; see README for what this does and does not prove.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re

from .corpus_en import EN
from .corpus_indic import HI, TA
from .pools import LABELS, R

HELD_OUT = {cls: ([len(fns) - 2, len(fns) - 1] if cls == "other" else [len(fns) - 1]) for cls, fns in EN.items()}

DISTRACTORS = [
    "Reference: FIR No. {n}/{y} registered at P.S. {ps}.",
    "The charge sheet in this matter was filed on {d}.",
    "The statement of the witness was recorded under Section 161.",
    "The FSL report is awaited.",
    "A copy of the medical report is annexed.",
    "See the seizure memo dated {d}.",
    "The court has issued a warrant against the absconding accused.",
    "Forwarded for information and necessary action.",
    "CONFIDENTIAL - FOR OFFICIAL USE ONLY",
    "Page {p} of {q}",
    "Copy for the case file. Received on {d}.",
]


def distract(text: str, r: R) -> str:
    if r.random() > 0.25:
        return text
    s = r.choice(DISTRACTORS).format(n=r.number(1, 900), y=r.year(), ps=r.station(), d=r.date(), p=r.number(1, 4), q=r.number(4, 9))
    return f"{s}\n{text}" if r.random() < 0.4 else f"{text.rstrip()}\n{s}\n"


_CONFUSE = [("O", "0"), ("l", "1"), ("I", "l"), ("S", "5"), ("B", "8"), ("rn", "m"), ("cl", "d"), ("e", "c"), ("a", "o")]


def ocr_noise(text: str, r: R, level: float) -> str:
    """Rough imitation of OCR damage: character confusions, dropped/merged characters and spaces, broken lines."""
    if level <= 0:
        return text
    out = []
    for ch in text:
        x = r.random()
        if x < level * 0.02:
            continue  # dropped character
        if x < level * 0.05 and ch == " ":
            continue  # merged words
        if x < level * 0.08 and ch.isascii():
            for a, b in _CONFUSE:
                if ch == a:
                    ch = b
                    break
        out.append(ch)
    s = "".join(out)
    if r.random() < level:
        s = re.sub(r"\n(?=[a-z])", " ", s)  # lines glued together
    if r.random() < level * 0.6:
        s = s.upper() if r.random() < 0.5 else s.lower()
    if r.random() < level * 0.5:
        s = re.sub(r"[.,;:()\"']", "", s)
    if r.random() < level * 0.5:
        s = re.sub(r" {1}", lambda m: "  " if r.random() < 0.2 else " ", s)
    return s


def structural_augment(text: str, r: R) -> str:
    """Breaks the link between a document's type and its layout, so the model has to read the content:
    drop the title block, shuffle lines, or keep only an excerpt (as when a scan is cropped or pages are missing)."""
    lines = [l for l in text.split("\n") if l.strip()]
    if len(lines) < 5:
        return text
    x = r.random()
    if x < 0.30:
        lines = lines[r.randint(1, 2):]
    elif x < 0.45:
        r.shuffle(lines)
    elif x < 0.60:
        start = r.randint(0, len(lines) - 3)
        lines = lines[start : start + r.randint(3, max(3, len(lines) - start))]
    return "\n".join(lines)


def _make(cls: str, lang: str, variant: int, r: R, noise: float, augment: bool = False) -> dict:
    fn = {"en": EN, "hi": HI, "ta": TA}[lang][cls][variant]
    text = distract(fn(r), r)
    if augment:
        text = structural_augment(text, r)
    text = ocr_noise(text, r, noise)
    return {"text": text.strip(), "label": cls, "lang": lang, "variant": variant}


def build(seed: int = 7, n_en: int = 200, n_hi: int = 60, n_ta: int = 40, n_val: int = 30) -> dict[str, list[dict]]:
    r = R(seed)
    train, val_seen, val_unseen, val_unseen_noisy = [], [], [], []
    for cls in LABELS:
        en_train_variants = [v for v in range(len(EN[cls])) if v not in HELD_OUT[cls]]
        for i in range(n_en):
            train.append(_make(cls, "en", en_train_variants[i % len(en_train_variants)], r, noise=r.choice([0, 0, 0.3, 0.6, 1.0]), augment=True))
        for lang, n, pool in (("hi", n_hi, HI), ("ta", n_ta, TA)):
            for i in range(n):
                train.append(_make(cls, lang, i % len(pool[cls]), r, noise=r.choice([0, 0, 0.3, 0.6]), augment=True))
        for i in range(n_val):
            val_seen.append(_make(cls, "en", en_train_variants[i % len(en_train_variants)], r, noise=r.choice([0, 0.3, 0.6])))
        for i in range(n_val):
            v = HELD_OUT[cls][i % len(HELD_OUT[cls])]
            val_unseen.append(_make(cls, "en", v, r, noise=0))
            val_unseen_noisy.append(_make(cls, "en", v, r, noise=1.0))
    r.shuffle(train)
    return {"train": train, "val_seen": val_seen, "val_unseen": val_unseen, "val_unseen_noisy": val_unseen_noisy}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data")
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    data = build(args.seed)
    for name, rows in data.items():
        with open(out / f"{name}.jsonl", "w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        langs = {l: sum(1 for x in rows if x["lang"] == l) for l in ("en", "hi", "ta")}
        print(f"{name:18s} {len(rows):5d} docs  {langs}")


if __name__ == "__main__":
    main()
