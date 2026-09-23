"""Scores a trained classifier exactly as the service would answer, across title-prior strengths.

    python -m training.evaluate --model models/classifier --data data --bonus 0,2,4,6,8 [--cpu] [--write BONUS]

Sets: val_unseen (held-out layouts), val_unseen_noisy (same + heavy OCR damage), llm_written (an independent
"author": documents written by the local LLM; labels come from the prompt so it carries some label noise).
Besides accuracy / macro-F1 it reports the two numbers that matter operationally:
  unflagged_error - wrong AND not marked needs_review   (mistakes a human would never be asked to look at)
  confident_error - wrong AND confidence >= 0.9
"""
from __future__ import annotations

import argparse
import json
import pathlib

import numpy as np
import torch
from sklearn.metrics import f1_score
from transformers import AutoModelForSequenceClassification, AutoTokenizer

from app.classifier import LABELS, Classifier
from training.train_classifier import L2I, load

SETS = {"val_unseen": "val_unseen.jsonl", "val_unseen_noisy": "val_unseen_noisy.jsonl", "llm_written": "llm_test.jsonl",
        "handwritten": "handwritten_test.jsonl"}


@torch.no_grad()
def logits_for(model, tok, rows, max_len, device, temperature, batch=32):
    out = []
    for i in range(0, len(rows), batch):
        enc = tok([r["text"][:6000] for r in rows[i : i + batch]], truncation=True, max_length=max_len, padding=True, return_tensors="pt").to(device)
        out.append(model(**enc).logits.float().cpu().numpy() / temperature)
    return np.concatenate(out)


def score(clf: Classifier, rows, logits) -> dict:
    y = np.array([L2I[r["label"]] for r in rows])
    res = [clf._finish(r["text"], lg) for r, lg in zip(rows, logits)]
    pred = np.array([LABELS.index(x["doc_type"]) for x in res])
    wrong = pred != y
    flagged = np.array([x["needs_review"] for x in res])
    conf = np.array([x["confidence"] for x in res])
    return {
        "n": len(rows), "accuracy": float((~wrong).mean()), "macro_f1": float(f1_score(y, pred, average="macro", labels=range(len(LABELS)), zero_division=0)),
        "review_rate": float(flagged.mean()), "unflagged_error": float((wrong & ~flagged).mean()), "confident_error": float((wrong & (conf >= 0.9)).mean()),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="models/classifier")
    ap.add_argument("--data", default="data")
    ap.add_argument("--bonus", default="0,2,4,6,8")
    ap.add_argument("--cpu", action="store_true")
    ap.add_argument("--write", type=float, default=None, help="store the results and this chosen bonus in metrics.json")
    args = ap.parse_args()

    device = torch.device("cpu" if args.cpu or not torch.cuda.is_available() else "cuda")
    path, data = pathlib.Path(args.model), pathlib.Path(args.data)
    tok = AutoTokenizer.from_pretrained(path)
    model = AutoModelForSequenceClassification.from_pretrained(path).to(device).eval()
    metrics = json.loads((path / "metrics.json").read_text())
    temperature, max_len = json.loads((path / "calibration.json").read_text())["temperature"], metrics.get("max_len", 256)
    sets = {n: load(data / f) for n, f in SETS.items() if (data / f).exists()}
    logits = {n: logits_for(model, tok, rows, max_len, device, temperature) for n, rows in sets.items()}

    clf = Classifier(path)
    results: dict[str, dict] = {}
    print(f"{'bonus':>5} | {'set':17} {'n':>4} {'acc':>6} {'F1':>6} {'review':>7} {'unflagged_err':>13} {'confident_err':>13}")
    for b in [float(x) for x in args.bonus.split(",")]:
        clf.title_bonus = b
        for name, rows in sets.items():
            m = score(clf, rows, logits[name])
            results.setdefault(str(b), {})[name] = m
            print(f"{b:5.1f} | {name:17} {m['n']:4d} {m['accuracy']:6.3f} {m['macro_f1']:6.3f} {m['review_rate']:7.3f} {m['unflagged_error']:13.3f} {m['confident_error']:13.3f}")
    if args.write is not None:
        metrics["hybrid"] = {"title_bonus": args.write, **results[str(args.write)]}
        metrics["hybrid_grid"] = results
        (path / "metrics.json").write_text(json.dumps(metrics, indent=2, ensure_ascii=False))
        print(f"wrote hybrid results for bonus={args.write} to {path / 'metrics.json'}")


if __name__ == "__main__":
    main()
