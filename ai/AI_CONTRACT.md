# AI service contract (v2)

The SDMS backend never imports a model. It talks to an **AI service** over HTTP. The implementation shipped in
[`/ai`](../ai) (OCR, fine-tuned classifier, entity extraction, multilingual embeddings, local-LLM summaries) follows this
contract; any other service that implements it can replace it without changing the rest of the system.

| Env var (backend) | Meaning |
|---|---|
| `SDMS_AI_SERVICE_URL` | Base URL, e.g. `http://127.0.0.1:9000`. Unset = the built-in rule-based stub (no scanned-image OCR, no embeddings, no summaries). |
| `SDMS_AI_SERVICE_KEY` | Shared secret sent as `X-Internal-Key` on every call. Required whenever the URL is set. |
| `SDMS_AI_TIMEOUT_SECONDS` | Per-call timeout (default 120). |

**Data residency:** the service runs on the same machine/network as SDMS and makes no external API calls at run time.
Models are baked into its image or served by a local Ollama; document text is never logged.

**Failure policy:** the AI layer is best-effort. If the service is down, slow, or returns something malformed, SDMS still
files the document (hash → encrypt → anchor) with empty extracted text and `ai_provider = "unavailable (...)"`. Nothing the
AI returns influences access control, hashing or the ledger - it is only searchable metadata shown to authorised officers.

## `POST /ai/process`

`multipart/form-data`: `file` (original bytes, ≤ 30 MB; PDF, PNG, JPEG, TIFF, DOCX, TXT) and optional `deep` (`true` by default:
also ask the LLM to enrich people / places / organisations - slower, skipped if the LLM is unavailable).

```json
{
  "ocr": {"text": "...", "confidence": 0.94, "language": "eng", "pages": [1], "method": "tesseract_pdf", "needs_review": false},
  "classification": {"doc_type": "fir", "confidence": 0.91, "scores": {"fir": 0.91, "charge_sheet": 0.05}},
  "entities": {"persons": ["Ramesh Kumar"], "locations": ["Kotwali"], "dates": ["12/03/2026"], "sections": ["379 IPC"],
               "case_numbers": ["142/2026"], "phones": ["9876543210"], "vehicles": ["UP 32 AB 1234"], "amounts": ["Rs. 45,000"],
               "people_roles": ["Ramesh Kumar — complainant"], "organizations": []},
  "tags": ["fir", "theft"],
  "embedding": [0.012, -0.044, "... 384 floats, L2-normalised ..."],
  "engine": "sentinel-ai-1.0",
  "models": {"classifier": "sentinel-classifier", "embedder": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2", "llm": null}
}
```

| Field | Notes |
|---|---|
| `ocr.method` | `pymupdf_native`, `tesseract_pdf`, `tesseract_image`, `docx_native`, `text_native` (`+truncated` if the page/time budget was hit). |
| `ocr.language` | Tesseract code: `eng`, `hin`, `tam` (or `eng+hin+tam` when undetermined). |
| `ocr.needs_review` | `true` = a human should look: low OCR confidence, truncated, or the classifier is unsure / disagrees with the document's own title. |
| `classification.doc_type` | One of `fir`, `police_report`, `investigation_record`, `witness_statement`, `charge_sheet`, `court_filing`, `evidence_record`, `forensic_report`, `legal_notice`, `judgment`, `medical_report`, `arrest_warrant`, `other`. Unknown values are stored as `other`. |
| `entities` | Any keys are accepted (≤ 25 values each). All values are indexed for search (through an encrypted blind index). |
| `embedding` | Fixed dimension for a given model; SDMS only compares vectors of equal length. `null` if unavailable. |

## `POST /ai/embed`

`{"texts": ["...", ...]}` (≤ 16) → `{"vectors": [[...]], "dim": 384, "model": "..."}`. Used to embed search queries; must be the same model as
`/ai/process` so queries and documents live in one vector space.

## `POST /ai/summarize`

`{"text": "..."}` → `{"summary": "...", "model": "sentinel-legal"}`. `503` if the LLM is unavailable. Called on demand from the UI
(too slow to run on every upload).

## `POST /ai/summarize-case`

`{"documents": [{"text": "...", "doc_type": "fir"}, ...]}` (≤ 12) → `{"overall": "...", "by_type": {"fir": "..."}, "documents": 3}`.

## `GET /ai/health` (no key)

Reports model state (`ready` / `loading` / `failed`), the classifier's **measured accuracy on held-out and independent test
sets** (not its training score), the embedding model, and whether Ollama is reachable.
