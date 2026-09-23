"""Downloads real, publicly-licensed Indian court records to add authentic (non-synthetic, non-LLM) text to the
"judgment" class - the one class for which real public data actually exists (FIRs and chargesheets are not public
records; see ai/README.md).

Source: KanoonGPT/indian-case-laws (Apache-2.0) - real case captions/dispositions from Indian High Courts. Fetches
one year's parquet shard directly over HTTP (a few tens of MB, with progress) instead of using `datasets` streaming
mode, which was observed to iterate this dataset extremely slowly with no usable progress signal.

Writes ai/data/real_judgments.jsonl in the same schema as llm_train.jsonl. Does not train anything - see
ai/README.md "Training offline" to use the file afterwards.

    .venv-train\\Scripts\\python -m training.download_real_judgments [--year 2005]
"""
from __future__ import annotations

import argparse
import json
import pathlib

import httpx
import pyarrow.parquet as pq

DATA = pathlib.Path(__file__).resolve().parent.parent / "data"
OUT = DATA / "real_judgments.jsonl"
MAX_PER_COURT = 25
TARGET = 700
URL_T = ("https://huggingface.co/datasets/KanoonGPT/indian-case-laws/resolve/main/"
         "structured/v1/year={y}/indian_case_laws_structured_v1_year={y}.parquet")


def download(year: int) -> pathlib.Path:
    dest = DATA / f"_kanoon_{year}.parquet"
    if dest.exists():
        print(f"{dest.name} already downloaded ({dest.stat().st_size / 1e6:.1f} MB)")
        return dest
    url = URL_T.format(y=year)
    print(f"downloading {url}")
    with httpx.stream("GET", url, timeout=120, follow_redirects=True) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        got = 0
        next_report = 5_000_000
        with open(dest, "wb") as f:
            for chunk in r.iter_bytes(1 << 20):
                f.write(chunk)
                got += len(chunk)
                if got >= next_report:
                    pct = f" ({100 * got / total:.0f}%)" if total else ""
                    print(f"  {got / 1e6:.1f} MB downloaded{pct}", flush=True)
                    next_report += 5_000_000
    print(f"done: {got / 1e6:.1f} MB -> {dest}")
    return dest


def convert(path: pathlib.Path) -> list[dict]:
    table = pq.read_table(path, columns=[
        "court_name", "party_petitioner", "party_respondent", "disposition_text", "indexable_text", "quality_json",
    ])
    df = table.to_pandas()
    rows: list[dict] = []
    per_court: dict[str, int] = {}
    for _, r in df.iterrows():
        if len(rows) >= TARGET:
            break
        try:
            q = json.loads(r["quality_json"])
        except (TypeError, ValueError):
            continue
        if q.get("error_count", 1) != 0 or q.get("missing_required_count", 1) != 0:
            continue
        if not r["party_petitioner"] or not r["party_respondent"] or not r["disposition_text"]:
            continue
        text = (r["indexable_text"] or "").strip()
        if len(text) < 80:
            continue
        court = r["court_name"] or "unknown"
        if per_court.get(court, 0) >= MAX_PER_COURT:
            continue
        per_court[court] = per_court.get(court, 0) + 1
        rows.append({"text": text, "label": "judgment", "lang": "en", "variant": -1, "source": "real"})
    print(f"kept {len(rows)} rows (of {len(df)} in the shard) across {len(per_court)} courts")
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=2005)
    args = ap.parse_args()

    parquet_path = download(args.year)
    rows = convert(parquet_path)
    DATA.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"wrote {len(rows)} real judgment rows to {OUT}")
    parquet_path.unlink()
    print(f"removed the intermediate parquet file ({parquet_path.name})")


if __name__ == "__main__":
    main()
