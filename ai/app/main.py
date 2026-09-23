"""SentinelDMS AI service: OCR, classification, entity extraction, embeddings and LLM summaries - all local.

Implements docs/AI_CONTRACT.md. Nothing here calls the internet at run time (models are baked into the image or come
from the local Ollama server); document text is never logged.
"""
from __future__ import annotations

import hmac
import logging
import os
import threading
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from pydantic import BaseModel, Field

from . import entities, ocr
from .classifier import Classifier
from .embedder import Embedder
from .llm import LLMUnavailable, Ollama

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
log = logging.getLogger("sentinel")

KEY = os.getenv("AI_SERVICE_KEY", "")
MODELS = Path(os.getenv("MODELS_DIR", "/models"))
MAX_UPLOAD = int(os.getenv("MAX_UPLOAD_MB", "30")) * 1024 * 1024
VERSION = "1.0"

if len(KEY) < 16:
    raise RuntimeError("AI_SERVICE_KEY must be set (16+ characters)")

app = FastAPI(title="SentinelDMS AI", version=VERSION, docs_url=None, redoc_url=None, openapi_url=None)
clf = Classifier(MODELS / "classifier")
emb = Embedder(MODELS)
llm = Ollama()
_heavy = threading.BoundedSemaphore(int(os.getenv("MAX_CONCURRENT_PROCESS", "2")))


def auth(x_internal_key: str | None = Header(None)) -> None:
    if not x_internal_key or not hmac.compare_digest(x_internal_key.encode(), KEY.encode()):
        raise HTTPException(401, "Invalid or missing X-Internal-Key")


@app.on_event("startup")
def warm() -> None:
    """Load the models in the background so the first real upload doesn't pay for it."""
    def go():
        try:
            clf.ready, emb.dim  # noqa: B018  (properties load the models)
            log.info("models ready: %s | embedder %s", clf.info.get("engine"), emb.name)
        except Exception:
            log.exception("model warm-up failed (will retry on first use)")
    threading.Thread(target=go, daemon=True).start()


@app.get("/ai/health")
def health() -> dict:
    return {"status": "ok", "version": VERSION, "classifier": clf.status(),
            "embedder": emb.name, "llm": llm.status()}


def _merge(base: dict[str, list[str]], extra: dict[str, list[str]]) -> dict[str, list[str]]:
    out = {k: list(v) for k, v in base.items()}
    for k, vals in extra.items():
        have = {x.lower() for x in out.get(k, [])}
        out.setdefault(k, []).extend(v for v in vals if v.lower() not in have)
    return {k: v[:25] for k, v in out.items() if v}


@app.post("/ai/process", dependencies=[Depends(auth)])
def process(file: UploadFile = File(...), deep: bool = Form(True)) -> dict:
    data = file.file.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "file too large")
    with _heavy:
        try:
            o = ocr.extract(data, file.filename or "")
        except ValueError as exc:
            raise HTTPException(415, str(exc))
        except Exception:
            log.exception("text extraction failed")
            o = {"text": "", "confidence": 0.0, "language": ocr.DEFAULT_LANG, "pages": [], "method": "failed", "needs_review": True}
        text = o["text"]
        cls = clf.classify(text)
        ents = entities.extract(text)
        llm_used = False
        if deep and len(text) >= 40:
            try:
                ents = _merge(ents, llm.extract_people(text))
                llm_used = True
            except LLMUnavailable as exc:
                log.info("LLM enrichment skipped: %s", exc)
        vec = emb.embed([text])[0] if text.strip() else None

    tags: list[str] = []
    for label, score in [(cls["doc_type"], 1.0), *cls["scores"].items()]:
        if label != "other" and (score >= 0.15) and label not in tags:
            tags.append(label)
    tags += [t for t in entities.offence_tags(ents.get("sections", [])) if t not in tags]
    return {
        "ocr": {**{k: o[k] for k in ("text", "confidence", "language", "pages", "method")},
                "needs_review": bool(o["needs_review"] or cls["needs_review"])},
        "classification": {"doc_type": cls["doc_type"], "confidence": cls["confidence"], "scores": cls["scores"]},
        "entities": ents, "tags": tags[:10], "embedding": vec,
        "engine": f"sentinel-ai-{VERSION}",
        "models": {"classifier": cls["engine"], "embedder": emb.name, "llm": llm._model if llm_used else None},
    }


class EmbedIn(BaseModel):
    texts: list[str] = Field(min_length=1, max_length=16)


@app.post("/ai/embed", dependencies=[Depends(auth)])
def embed(body: EmbedIn) -> dict:
    vecs = emb.embed([t[:20000] for t in body.texts])
    return {"vectors": vecs, "dim": len(vecs[0]), "model": emb.name}


class SummarizeIn(BaseModel):
    text: str = Field(min_length=1, max_length=400_000)


@app.post("/ai/summarize", dependencies=[Depends(auth)])
def summarize(body: SummarizeIn) -> dict:
    try:
        summary, removed = llm.summarize(body.text)
        return {"summary": summary or None, "model": llm._model, "removed_claims": len(removed)}
    except LLMUnavailable as exc:
        raise HTTPException(503, str(exc))


class CaseDoc(BaseModel):
    text: str = Field(max_length=400_000)
    doc_type: str | None = None


class CaseIn(BaseModel):
    documents: list[CaseDoc] = Field(min_length=1, max_length=12)


@app.post("/ai/summarize-case", dependencies=[Depends(auth)])
def summarize_case(body: CaseIn) -> dict:
    try:
        return llm.summarize_case([d.model_dump() for d in body.documents])
    except LLMUnavailable as exc:
        raise HTTPException(503, str(exc))
