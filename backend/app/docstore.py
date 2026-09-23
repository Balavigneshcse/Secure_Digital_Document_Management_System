"""Document metadata in MongoDB.

One record per document *version*, keyed "<document_id>:<version_no>":
  * content_enc  - OCR text, language, entities, summary: AES-256-GCM sealed (bound to the record key)
  * kw           - blind-index tokens (keyed HMAC of each word): exact-word search without plaintext in the DB
  * embedding    - float32 vector for semantic search (needs plaintext for similarity; see README limitations)
  * tags/doc_type/etc. - non-sensitive classification labels, stored in clear

Which version is "current" is decided by PostgreSQL (documents.current_version); search first scopes
candidates there, then asks Mongo about exactly those keys, so there's no cross-store flag to keep in sync.
"""
from __future__ import annotations

import numpy as np
from bson import Binary

from .crypto import blind_tokens, open_json, seal_json, tokenize
from .mongo import Mongo


def meta_key(document_id: int, version_no: int) -> str:
    return f"{document_id}:{version_no}"


def _index_text(content: dict) -> str:
    parts = [content.get("ocr_text") or ""]
    for vals in (content.get("entities") or {}).values():
        parts.extend(vals)
    parts.append(content.get("summary") or "")
    return " ".join(parts)


def put_meta(
    mongo: Mongo, kek: bytes, *, document_id: int, version_no: int, case_number: str, case_id: int,
    uploaded_at: str, doc_type: str, doc_confidence: float | None, provider: str | None,
    tags: list[str], content: dict, embedding: list[float] | None,
) -> str:
    key = meta_key(document_id, version_no)
    mongo.doc_meta.insert_one({
        "_id": key, "document_id": document_id, "version_no": version_no, "case_number": case_number,
        "case_id": case_id, "uploaded_at": uploaded_at, "doc_type": doc_type, "doc_confidence": doc_confidence,
        "provider": provider, "tags": tags,
        "kw": blind_tokens(kek, _index_text(content)),
        "content_enc": seal_json(kek, content, key.encode()),
        "embedding": Binary(np.asarray(embedding, dtype="<f4").tobytes()) if embedding else None,
        "embedding_dim": len(embedding) if embedding else 0,
    })
    return key


def delete_meta(mongo: Mongo, document_id: int, version_no: int) -> None:
    mongo.doc_meta.delete_one({"_id": meta_key(document_id, version_no)})


def update_content(mongo: Mongo, kek: bytes, document_id: int, version_no: int, **fields) -> dict:
    """Merges fields (e.g. summary) into the sealed content and refreshes the search tokens."""
    key = meta_key(document_id, version_no)
    rec = mongo.doc_meta.find_one({"_id": key}, {"content_enc": 1})
    if rec is None:
        raise KeyError(key)
    content = open_json(kek, rec["content_enc"], key.encode())
    content.update(fields)
    mongo.doc_meta.update_one(
        {"_id": key},
        {"$set": {"content_enc": seal_json(kek, content, key.encode()), "kw": blind_tokens(kek, _index_text(content))}},
    )
    return content


def load_contents(mongo: Mongo, kek: bytes, keys: list[str]) -> dict[str, dict]:
    """Decrypts the sealed content of the given records (callers must already have authorised access)."""
    out: dict[str, dict] = {}
    if not keys:
        return out
    for rec in mongo.doc_meta.find({"_id": {"$in": keys}}, {"content_enc": 1, "tags": 1}):
        content = open_json(kek, rec["content_enc"], rec["_id"].encode())
        content["_tags"] = rec.get("tags") or []
        out[rec["_id"]] = content
    return out


def keyword_matches(mongo: Mongo, kek: bytes, keys: list[str], query: str) -> set[str]:
    """Keys (among `keys`) whose text contains every word of `query`. Whole-word match, case-insensitive."""
    words = tokenize(query)
    if not words or not keys:
        return set()
    # Re-derive the same tokens the index holds, by running the query through the same keyed hash.
    hashed = blind_tokens(kek, " ".join(words))
    cur = mongo.doc_meta.find({"_id": {"$in": keys}, "kw": {"$all": hashed}}, {"_id": 1})
    return {r["_id"] for r in cur}


def semantic_top(mongo: Mongo, keys: list[str], query_vec: list[float], k: int = 10, min_score: float = 0.25) -> list[tuple[str, float]]:
    """Cosine similarity over the embeddings of exactly the (already permission-scoped) `keys`."""
    if not keys or not query_vec:
        return []
    dim = len(query_vec)
    ids, rows = [], []
    for rec in mongo.doc_meta.find({"_id": {"$in": keys}, "embedding_dim": dim}, {"embedding": 1}):
        if rec.get("embedding"):
            ids.append(rec["_id"])
            rows.append(np.frombuffer(bytes(rec["embedding"]), dtype="<f4"))
    if not ids:
        return []
    mat = np.vstack(rows)
    q = np.asarray(query_vec, dtype="float32")
    mat = mat / np.clip(np.linalg.norm(mat, axis=1, keepdims=True), 1e-9, None)
    q = q / max(float(np.linalg.norm(q)), 1e-9)
    scores = mat @ q
    order = np.argsort(-scores)[:k]
    return [(ids[i], float(scores[i])) for i in order if scores[i] >= min_score]
