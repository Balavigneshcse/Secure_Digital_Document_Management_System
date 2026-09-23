"""Client for the local AI service (docs/AI_CONTRACT.md)."""
from __future__ import annotations

import httpx

from . import AIResult, AIServiceError


class HttpAI:
    name = "sentinel-ai"

    def __init__(self, base_url: str, api_key: str, timeout: float = 120.0, transport: httpx.BaseTransport | None = None):
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"), headers={"X-Internal-Key": api_key}, timeout=timeout, transport=transport
        )

    def _post(self, path: str, **kw) -> dict:
        try:
            r = self._client.post(path, **kw)
            r.raise_for_status()
            j = r.json()
            if not isinstance(j, dict):
                raise ValueError("expected a JSON object")
            return j
        except (httpx.HTTPError, ValueError) as exc:
            raise AIServiceError(f"{path} failed: {exc}") from exc

    def process(self, filename: str, content_type: str, data: bytes) -> AIResult:
        j = self._post("/ai/process", files={"file": (filename, data, content_type)}, data={"deep": "true"})
        try:
            ocr, cls = j.get("ocr") or {}, j.get("classification") or {}
            emb = j.get("embedding")
            return AIResult(
                text=str(ocr.get("text", "")), language=ocr.get("language"),
                ocr_confidence=float(ocr.get("confidence", 0.0)), ocr_method=str(ocr.get("method", "external")),
                pages=[int(p) for p in ocr.get("pages", [])], needs_review=bool(ocr.get("needs_review", False)),
                doc_type=str(cls.get("doc_type", "other")), doc_confidence=float(cls.get("confidence", 0.0)),
                scores={str(k): float(v) for k, v in (cls.get("scores") or {}).items()},
                tags=[str(t) for t in j.get("tags", [])],
                entities={str(k): [str(x) for x in v] for k, v in (j.get("entities") or {}).items()},
                embedding=[float(x) for x in emb] if emb else None,
                engine=str(j.get("engine", "external")),
            )
        except (ValueError, TypeError, AttributeError) as exc:
            raise AIServiceError(f"/ai/process returned a malformed response: {exc}") from exc

    def embed(self, text: str) -> list[float] | None:
        j = self._post("/ai/embed", json={"texts": [text]})
        vecs = j.get("vectors") or []
        return [float(x) for x in vecs[0]] if vecs else None

    def summarize(self, text: str) -> str | None:
        return self._post("/ai/summarize", json={"text": text}).get("summary")

    def summarize_case(self, documents: list[dict]) -> dict | None:
        return self._post("/ai/summarize-case", json={"documents": documents})
