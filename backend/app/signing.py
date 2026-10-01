"""Digital signatures on document versions (Ed25519).

Each user gets a key pair the first time they sign. The private key is sealed with the master key, so this is a
server-held key unlocked by the user's session plus their password - not a personal smart card, DSC token or
Aadhaar eSign, which a production system would use instead. The public key is anchored on the ledger when it is
created: a signature only counts as valid if the key that made it is the one the ledger recorded for that user, so
an attacker who swaps keys in the database cannot forge a valid-looking signature.
"""
from __future__ import annotations

import base64
import json

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from sqlalchemy.orm import Session

from .crypto import decrypt_field, encrypt_field
from .db import utcnow
from .ledger import canonical
from .models import Document, DocumentVersion, Signature, SigningKey, User

KEY_KIND = "SIGNING_KEY"


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode()


def get_or_create_key(state, db: Session, user: User) -> SigningKey:
    key = db.get(SigningKey, user.id)
    if key is not None:
        return key
    priv = Ed25519PrivateKey.generate()
    pub = _b64(priv.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw))
    raw = priv.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
    now = utcnow()
    block = state.ledger.anchor(KEY_KIND, {"user_id": user.id, "username": user.username, "public_key": pub, "created_at": now})
    key = SigningKey(user_id=user.id, public_key=pub, private_key_enc=encrypt_field(state.kek, _b64(raw)), created_at=now,
                     ledger_tx_id=block.tx_id or block.block_hash)
    db.add(key)
    db.flush()
    return key


def statement_for(doc: Document, v: DocumentVersion, user: User, signed_at: str) -> str:
    """What is signed: the exact file (by its SHA-256), which document and version it is, who signs and when."""
    return canonical({
        "purpose": "SDMS document signature", "document_uid": doc.uid, "document_id": doc.id, "case_number": doc.case.case_number,
        "version_no": v.version_no, "sha256": v.sha256, "signer_id": user.id, "signer_username": user.username,
        "signer_role": user.role, "signed_at": signed_at,
    })


def sign(state, key: SigningKey, statement: str) -> str:
    priv = Ed25519PrivateKey.from_private_bytes(base64.b64decode(decrypt_field(state.kek, key.private_key_enc)))
    return _b64(priv.sign(statement.encode()))


def check(state, db: Session, doc: Document, v: DocumentVersion, sig: Signature) -> list[str]:
    """Problems with one signature; an empty list means it is valid."""
    problems = []
    try:
        Ed25519PublicKey.from_public_bytes(base64.b64decode(sig.public_key)).verify(
            base64.b64decode(sig.signature), sig.statement.encode())
    except (InvalidSignature, ValueError):
        problems.append("The signature does not match what was signed")
    try:
        st = json.loads(sig.statement)
    except ValueError:
        st = {}
    if (st.get("document_uid"), st.get("version_no"), st.get("sha256"), st.get("signer_id")) != (doc.uid, v.version_no, v.sha256, sig.signer_id):
        problems.append("What was signed is not this version of this document")
    key = db.get(SigningKey, sig.signer_id)
    if key is None or key.public_key != sig.public_key:
        problems.append("The signer's key on record is not the key that made this signature")
    else:
        try:
            block = state.ledger.get_by_tx(key.ledger_tx_id) if key.ledger_tx_id else None
        except Exception:  # ledger unreachable: say so rather than call it valid
            problems.append("The ledger could not be reached to confirm the signer's key")
        else:
            if block is None or block.payload.get("public_key") != sig.public_key or block.payload.get("user_id") != sig.signer_id:
                problems.append("The signer's key does not match the key registered on the ledger")
    return problems
