"""Fine-tunes a multilingual transformer to classify legal / investigation documents.

    python -m training.train_classifier --data data --out models/classifier

Checkpoint selection uses `val_seen` only. `val_unseen` (layouts never seen in training) and `val_unseen_noisy`
are reported at the end and never influence training, so they are an honest generalisation check
(within the limits of synthetic data - see ai/README.md).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import time

import numpy as np
import torch
from sklearn.metrics import classification_report, confusion_matrix, f1_score
from transformers import AutoModelForSequenceClassification, AutoTokenizer, get_linear_schedule_with_warmup

from .pools import LABELS

BASE = "distilbert-base-multilingual-cased"
L2I = {l: i for i, l in enumerate(LABELS)}


_MD = re.compile(r"(\*\*|__|^#{1,6}\s*|`+)", re.M)


def clean_llm(text: str) -> str:
    """LLM output carries markdown (**bold**, # headings) that real documents don't; strip it so it can't
    become a shortcut ("has asterisks -> written by the generator")."""
    text = re.sub(r"\\([\\`*_{}\[\]()#+\-.!|])", r"\1", text)  # markdown escapes such as "1\." or "\-"
    return re.sub(r"\n{3,}", "\n\n", _MD.sub("", text)).strip()


def load(path: pathlib.Path, exclude_lang: set[str] = frozenset()) -> list[dict]:
    rows = [json.loads(l) for l in open(path, encoding="utf-8")]
    for r in rows:
        if r.get("source") == "llm":
            r["text"] = clean_llm(r["text"])
    return [r for r in rows if r["lang"] not in exclude_lang]


def batches(tok, rows, batch_size, max_len, shuffle, rng, device):
    idx = np.arange(len(rows))
    if shuffle:
        rng.shuffle(idx)
    for i in range(0, len(idx), batch_size):
        chunk = [rows[j] for j in idx[i : i + batch_size]]
        enc = tok([r["text"] for r in chunk], truncation=True, max_length=max_len, padding=True, return_tensors="pt")
        yield {k: v.to(device) for k, v in enc.items()}, torch.tensor([L2I[r["label"]] for r in chunk], device=device)


@torch.no_grad()
def predict_logits(model, tok, rows, max_len, device, batch_size=64) -> np.ndarray:
    model.eval()
    out = []
    for enc, _ in batches(tok, rows, batch_size, max_len, False, None, device):
        with torch.autocast(device_type=device.type, dtype=torch.float16, enabled=device.type == "cuda"):
            out.append(model(**enc).logits.float().cpu().numpy())
    return np.concatenate(out) if out else np.zeros((0, len(LABELS)))


def metrics(logits: np.ndarray, rows: list[dict]) -> dict:
    y = np.array([L2I[r["label"]] for r in rows])
    pred = logits.argmax(1)
    return {"n": len(rows), "accuracy": float((pred == y).mean()), "macro_f1": float(f1_score(y, pred, average="macro", labels=range(len(LABELS))))}


def fit_temperature(logits: np.ndarray, y: np.ndarray) -> float:
    """Single temperature T minimising NLL on held-back data, so confidence scores mean what they say."""
    z = torch.tensor(logits, dtype=torch.float32)
    t = torch.tensor(y)
    log_t = torch.zeros(1, requires_grad=True)
    opt = torch.optim.LBFGS([log_t], lr=0.1, max_iter=100)

    def closure():
        opt.zero_grad()
        loss = torch.nn.functional.cross_entropy(z / log_t.exp(), t)
        loss.backward()
        return loss

    opt.step(closure)
    return float(log_t.exp().item())


def ece(probs: np.ndarray, y: np.ndarray, bins: int = 10) -> float:
    conf, pred = probs.max(1), probs.argmax(1)
    err, edges = 0.0, np.linspace(0, 1, bins + 1)
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (conf > lo) & (conf <= hi)
        if m.any():
            err += m.mean() * abs((pred[m] == y[m]).mean() - conf[m].mean())
    return float(err)


def softmax(z: np.ndarray) -> np.ndarray:
    z = z - z.max(1, keepdims=True)
    e = np.exp(z)
    return e / e.sum(1, keepdims=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    ap.add_argument("--out", default="models/classifier")
    ap.add_argument("--base", default=BASE)
    ap.add_argument("--epochs", type=int, default=4)
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--lr", type=float, default=4e-5)
    ap.add_argument("--max-len", type=int, default=256)
    ap.add_argument("--seed", type=int, default=13)
    ap.add_argument("--exclude-lang", default="", help="comma list, e.g. ta: train without a language (zero-shot experiment)")
    ap.add_argument("--extra", default=None, help="comma-separated JSONL files of extra labelled rows (LLM-written docs, officer corrections)")
    ap.add_argument("--extra-repeat", type=int, default=4, help="times each --extra row is included (re-augmented each time)")
    ap.add_argument("--train-embeddings", action="store_true")
    args = ap.parse_args()

    torch.manual_seed(args.seed)
    rng = np.random.default_rng(args.seed)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    data = pathlib.Path(args.data)
    excl = {x for x in args.exclude_lang.split(",") if x}
    train = load(data / "train.jsonl", excl)
    extra_rows: list[dict] = []
    for extra in filter(None, (args.extra or "").split(",")):
        extra_rows += load(pathlib.Path(extra))
    if extra_rows:  # few but diverse: repeat each one, re-augmented every time, so they aren't drowned out by the templates
        from .corpus import ocr_noise, structural_augment
        from .pools import R

        rr = R(args.seed + 1)
        for row in extra_rows:
            train.append(row)
            for _ in range(max(0, args.extra_repeat - 1)):
                train.append({**row, "text": ocr_noise(structural_augment(row["text"], rr), rr, rr.choice([0, 0, 0.3, 0.6]))})
        print(f"extra rows: {len(extra_rows)} x {args.extra_repeat} = {len(extra_rows) * args.extra_repeat} training examples")
    val_seen = load(data / "val_seen.jsonl")
    tests = {"val_unseen": load(data / "val_unseen.jsonl"), "val_unseen_noisy": load(data / "val_unseen_noisy.jsonl")}
    if (data / "handwritten_test.jsonl").exists():
        tests["handwritten"] = load(data / "handwritten_test.jsonl")
    if (data / "llm_test.jsonl").exists():  # written by a different "author" (the local LLM) - the least biased test we have
        tests["llm_written"] = load(data / "llm_test.jsonl")
    print(f"device={device} train={len(train)} val_seen={len(val_seen)} excluded_langs={sorted(excl)}")

    tok = AutoTokenizer.from_pretrained(args.base)
    model = AutoModelForSequenceClassification.from_pretrained(
        args.base, num_labels=len(LABELS), id2label=dict(enumerate(LABELS)), label2id=L2I
    ).to(device)
    if not args.train_embeddings:  # the 92M-parameter word-embedding matrix dominates memory and barely helps here
        for n, p in model.named_parameters():
            if "word_embeddings" in n:
                p.requires_grad = False

    params = [p for p in model.parameters() if p.requires_grad]
    opt = torch.optim.AdamW(params, lr=args.lr, weight_decay=0.01)
    steps = args.epochs * ((len(train) + args.batch - 1) // args.batch)
    sched = get_linear_schedule_with_warmup(opt, int(0.1 * steps), steps)
    scaler = torch.amp.GradScaler(enabled=device.type == "cuda")

    best, best_state, history = -1.0, None, []
    t0 = time.time()
    for epoch in range(1, args.epochs + 1):
        model.train()
        total, n = 0.0, 0
        for enc, y in batches(tok, train, args.batch, args.max_len, True, rng, device):
            with torch.autocast(device_type=device.type, dtype=torch.float16, enabled=device.type == "cuda"):
                loss = torch.nn.functional.cross_entropy(model(**enc).logits.float(), y, label_smoothing=0.05)
            opt.zero_grad(set_to_none=True)
            scaler.scale(loss).backward()
            scaler.unscale_(opt)
            torch.nn.utils.clip_grad_norm_(params, 1.0)
            scaler.step(opt)
            scaler.update()
            sched.step()
            total, n = total + loss.item() * len(y), n + len(y)
        m = metrics(predict_logits(model, tok, val_seen, args.max_len, device), val_seen)
        history.append({"epoch": epoch, "train_loss": total / n, "val_seen": m, "elapsed_s": round(time.time() - t0)})
        print(f"epoch {epoch}: loss {total / n:.4f} | val_seen acc {m['accuracy']:.4f} macro-F1 {m['macro_f1']:.4f} | {time.time() - t0:.0f}s")
        if m["macro_f1"] >= best:
            best = m["macro_f1"]
            best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}

    model.load_state_dict(best_state)
    val_logits = predict_logits(model, tok, val_seen, args.max_len, device)
    yv = np.array([L2I[r["label"]] for r in val_seen])
    temperature = fit_temperature(val_logits, yv)

    report = {"base_model": args.base, "labels": LABELS, "temperature": temperature, "max_len": args.max_len, "history": history,
              "trained_on": {"docs": len(train), "excluded_langs": sorted(excl), "extra": bool(args.extra)},
              "torch": torch.__version__, "seed": args.seed}
    print(f"\ntemperature = {temperature:.3f}")
    for name, rows in tests.items():
        lg = predict_logits(model, tok, rows, args.max_len, device)
        y = np.array([L2I[r["label"]] for r in rows])
        m = metrics(lg, rows)
        m["ece_calibrated"] = ece(softmax(lg / temperature), y)
        m["ece_uncalibrated"] = ece(softmax(lg), y)
        m["per_class"] = classification_report(y, lg.argmax(1), labels=range(len(LABELS)), target_names=LABELS, output_dict=True, zero_division=0)
        m["confusion"] = confusion_matrix(y, lg.argmax(1), labels=range(len(LABELS))).tolist()
        report[name] = m
        print(f"{name:18s} acc {m['accuracy']:.4f}  macro-F1 {m['macro_f1']:.4f}  ECE {m['ece_calibrated']:.3f} (uncalibrated {m['ece_uncalibrated']:.3f})")
        worst = sorted(((v["f1-score"], k) for k, v in m["per_class"].items() if k in LABELS))[:3]
        print("   weakest classes:", ", ".join(f"{k} F1={f:.2f}" for f, k in worst))
    if excl:  # zero-shot check on the language that was left out of training
        rows = [json.loads(l) for l in open(data / "train.jsonl", encoding="utf-8")]
        rows = [r for r in rows if r["lang"] in excl]
        m = metrics(predict_logits(model, tok, rows, args.max_len, device), rows)
        report[f"zero_shot_{'+'.join(sorted(excl))}"] = m
        print(f"zero-shot on excluded language(s) {sorted(excl)}: acc {m['accuracy']:.4f} macro-F1 {m['macro_f1']:.4f} (n={m['n']})")

    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(out)
    tok.save_pretrained(out)
    (out / "labels.json").write_text(json.dumps(LABELS))
    (out / "calibration.json").write_text(json.dumps({"temperature": temperature}))
    report["data_sha256"] = hashlib.sha256((data / "train.jsonl").read_bytes()).hexdigest()
    (out / "metrics.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"saved to {out}")


if __name__ == "__main__":
    main()
