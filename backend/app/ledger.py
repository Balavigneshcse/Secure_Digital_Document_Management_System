"""Integrity ledger interface.

`Ledger` is the seam the rest of the system depends on:
  * `FabricLedger` (app/fabric_ledger.py) - the real thing: Hyperledger Fabric, reached through the gateway service.
  * `MemoryLedger` (below) - an in-process hash chain used by the automated tests and nothing else.

Only hashes and minimal metadata are ever written; documents never touch the ledger.
"""
from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass
from typing import Protocol

from .db import utcnow

GENESIS_HASH = "0" * 64


def canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Block:
    """One anchored record. For Fabric: `tx_id` is the Fabric transaction id and `index` the block number
    that committed it; for MemoryLedger `tx_id` is the block hash."""

    index: int
    ts: str
    kind: str
    payload: dict
    payload_hash: str
    prev_hash: str
    block_hash: str
    tx_id: str = ""

    def as_dict(self) -> dict:
        return {
            "index": self.index, "ts": self.ts, "kind": self.kind, "payload": self.payload,
            "payload_hash": self.payload_hash, "prev_hash": self.prev_hash, "block_hash": self.block_hash,
            "tx_id": self.tx_id or self.block_hash,
        }


class Ledger(Protocol):
    def anchor(self, kind: str, payload: dict) -> Block: ...
    def get_by_tx(self, tx_id: str) -> Block | None: ...
    def verify_record(self, block: Block) -> bool: ...
    def verify_chain(self) -> dict: ...
    def blocks(self, offset: int = 0, limit: int = 50, kind: str | None = None) -> tuple[list[Block], int]: ...
    def latest(self, kind: str, scope: str | None = None) -> Block | None: ...
    def status(self) -> dict: ...


def compute_block_hash(index: int, ts: str, kind: str, payload_hash: str, prev_hash: str) -> str:
    return sha256_hex(f"{index}|{ts}|{kind}|{payload_hash}|{prev_hash}")


class MemoryLedger:
    """Hash-chained in-memory ledger. Tamper-evident within the process only - never used outside tests."""

    def __init__(self):
        self._lock = threading.Lock()
        self._blocks: list[Block] = []
        self._append("GENESIS", {"note": "SDMS memory ledger genesis"})

    def _append(self, kind: str, payload: dict) -> Block:
        index = len(self._blocks)
        prev = self._blocks[-1].block_hash if self._blocks else GENESIS_HASH
        ts = utcnow()
        payload = json.loads(canonical(payload))
        ph = sha256_hex(canonical(payload))
        bh = compute_block_hash(index, ts, kind, ph, prev)
        b = Block(index, ts, kind, payload, ph, prev, bh, tx_id=bh)
        self._blocks.append(b)
        return b

    def anchor(self, kind: str, payload: dict) -> Block:
        with self._lock:
            return self._append(kind, payload)

    def get_by_tx(self, tx_id: str) -> Block | None:
        with self._lock:
            return next((b for b in self._blocks if b.tx_id == tx_id), None)

    def verify_record(self, b: Block) -> bool:
        return b.payload_hash == sha256_hex(canonical(b.payload)) and b.block_hash == compute_block_hash(
            b.index, b.ts, b.kind, b.payload_hash, b.prev_hash
        )

    def latest(self, kind: str, scope: str | None = None) -> Block | None:
        """Most recent block of `kind`; with `scope`, only those whose payload carries that chain_id."""
        with self._lock:
            return next((b for b in reversed(self._blocks)
                         if b.kind == kind and (scope is None or b.payload.get("chain_id") == scope)), None)

    def blocks(self, offset: int = 0, limit: int = 50, kind: str | None = None) -> tuple[list[Block], int]:
        with self._lock:
            rows = [b for b in reversed(self._blocks) if not kind or b.kind == kind]
        return rows[offset : offset + limit], len(rows)

    def verify_chain(self) -> dict:
        with self._lock:
            blocks = list(self._blocks)
        prev = GENESIS_HASH
        for i, b in enumerate(blocks):
            if b.index != i:
                return {"ok": False, "checked": i, "broken_at": i, "reason": "missing block"}
            if b.prev_hash != prev:
                return {"ok": False, "checked": i, "broken_at": b.index, "reason": "broken hash link"}
            if not self.verify_record(b):
                return {"ok": False, "checked": i, "broken_at": b.index, "reason": "block content altered"}
            prev = b.block_hash
        return {"ok": True, "checked": len(blocks), "broken_at": None, "reason": None}

    def status(self) -> dict:
        return {"backend": "memory", "height": len(self._blocks)}

    def _tamper(self, index: int, payload: dict | None = None, ts: str | None = None) -> None:
        """Test hook: rewrite a stored block in place, as an attacker with storage access would."""
        with self._lock:
            b = self._blocks[index]
            self._blocks[index] = Block(
                b.index, ts or b.ts, b.kind, payload if payload is not None else b.payload,
                b.payload_hash, b.prev_hash, b.block_hash, b.tx_id,
            )
