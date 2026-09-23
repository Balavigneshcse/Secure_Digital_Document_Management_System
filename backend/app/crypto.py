"""Envelope encryption (AES-256-GCM).

Each stored file gets its own random data key (DEK). The DEK is wrapped with the key-encryption
key (KEK). In this prototype the KEK comes from config; production must fetch/unwrap through a
KMS or HSM so the application host never holds the KEK itself.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import unicodedata

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

NONCE_LEN = 12


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode()


def _unb64(s: str) -> bytes:
    return base64.b64decode(s)


def _seal(key: bytes, plaintext: bytes, aad: bytes) -> bytes:
    nonce = os.urandom(NONCE_LEN)
    return nonce + AESGCM(key).encrypt(nonce, plaintext, aad)


def _open(key: bytes, blob: bytes, aad: bytes) -> bytes:
    return AESGCM(key).decrypt(blob[:NONCE_LEN], blob[NONCE_LEN:], aad)


def encrypt_file(kek: bytes, plaintext: bytes, storage_key: str) -> tuple[bytes, str]:
    """Returns (ciphertext blob, wrapped DEK). The storage key is bound as AAD so a ciphertext
    copied under another version's key fails authentication."""
    dek = AESGCM.generate_key(bit_length=256)
    blob = _seal(dek, plaintext, storage_key.encode())
    wrapped = _b64(_seal(kek, dek, b"dek:" + storage_key.encode()))
    return blob, wrapped


def decrypt_file(kek: bytes, blob: bytes, wrapped_dek: str, storage_key: str) -> bytes:
    """Raises cryptography.exceptions.InvalidTag if the blob or wrapped key was modified."""
    dek = _open(kek, _unb64(wrapped_dek), b"dek:" + storage_key.encode())
    return _open(dek, blob, storage_key.encode())


def encrypt_field(kek: bytes, value: str) -> str:
    return _b64(_seal(kek, value.encode(), b"field"))


def decrypt_field(kek: bytes, token: str) -> str:
    return _open(kek, _unb64(token), b"field").decode()


# --- sealed JSON records (OCR text, entities, summaries) --------------------------------------------
def seal_json(kek: bytes, obj, aad: bytes) -> str:
    """AES-256-GCM over a JSON document, bound to `aad` (the record key) so it can't be moved to another record."""
    return _b64(_seal(_derive(kek, b"sdms-record-encryption"), json.dumps(obj, ensure_ascii=False).encode(), aad))


def open_json(kek: bytes, token: str, aad: bytes):
    return json.loads(_open(_derive(kek, b"sdms-record-encryption"), _unb64(token), aad))


# --- blind index: keyword search without storing searchable plaintext -------------------------------
def _derive(kek: bytes, info: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=info).derive(kek)


def tokenize(text: str) -> set[str]:
    """Unicode-aware word tokens (letters, digits and combining marks, so Devanagari/Tamil words stay whole)."""
    text = unicodedata.normalize("NFKC", text or "").casefold()
    out: set[str] = set()
    cur: list[str] = []
    for ch in text:
        if unicodedata.category(ch)[0] in "LNM":
            cur.append(ch)
        else:
            if len(cur) >= 2:
                out.add("".join(cur))
            cur = []
    if len(cur) >= 2:
        out.add("".join(cur))
    return out


def blind_tokens(kek: bytes, text: str, limit: int = 8000) -> list[str]:
    """Keyed HMAC of each token. Only someone holding the KEK can test whether a word is present."""
    key = _derive(kek, b"sdms-blind-index")
    toks = sorted(tokenize(text))[:limit]
    return [hmac.new(key, t.encode(), hashlib.sha256).hexdigest()[:24] for t in toks]
