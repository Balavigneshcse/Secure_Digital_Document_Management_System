"""Multilingual sentence embeddings for semantic search (English / Hindi / Tamil).

The reference package used all-mpnet-base-v2 (English only, 768-d). Documents here are often Hindi or Tamil, so this
uses a multilingual model (384-d). If a domain-fine-tuned model exists in models/embedder it is used instead.
"""
from __future__ import annotations

import logging
import os
import threading
from pathlib import Path

import numpy as np

log = logging.getLogger("sentinel.embedder")

BASE_MODEL = os.getenv("EMBED_MODEL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
CHUNK_WORDS = 160
MAX_CHUNKS = 4


class Embedder:
    def __init__(self, models_dir: Path):
        self.local = models_dir / "embedder"
        self._lock = threading.Lock()
        self._model = None
        self.name = BASE_MODEL

    def _get(self):
        with self._lock:
            if self._model is None:
                from sentence_transformers import SentenceTransformer

                src = str(self.local) if (self.local / "config.json").exists() or (self.local / "modules.json").exists() else BASE_MODEL
                self.name = "domain-finetuned:" + self.local.name if src == str(self.local) else BASE_MODEL
                self._model = SentenceTransformer(src, device="cpu")
                self._model.max_seq_length = 256
        return self._model

    @property
    def dim(self) -> int:
        return int(self._get().get_sentence_embedding_dimension())

    def embed(self, texts: list[str]) -> list[list[float]]:
        """One unit vector per text. Long texts are split into windows whose embeddings are averaged."""
        model = self._get()
        windows, owner = [], []
        for i, t in enumerate(texts):
            words = (t or "").split()
            chunks = [" ".join(words[j : j + CHUNK_WORDS]) for j in range(0, max(len(words), 1), CHUNK_WORDS)][:MAX_CHUNKS] or [""]
            windows.extend(chunks)
            owner.extend([i] * len(chunks))
        vecs = model.encode(windows, normalize_embeddings=True, batch_size=16, show_progress_bar=False)
        out = np.zeros((len(texts), vecs.shape[1]), dtype="float32")
        for v, o in zip(vecs, owner):
            out[o] += v
        out /= np.clip(np.linalg.norm(out, axis=1, keepdims=True), 1e-9, None)
        return out.tolist()
