"""Hyperledger Fabric ledger client.

Talks to the REST gateway in /fabric/gateway (there is no official Python Fabric client). Every anchor is a
Fabric transaction endorsed by both the Police and Court organisations and ordered into a block; the chain
itself is kept by the peers, outside this process and outside this database - which is what makes it
tamper-evident against someone who controls the application host.
"""
from __future__ import annotations

import httpx

from .ledger import Block, canonical, sha256_hex


class LedgerError(RuntimeError):
    pass


class FabricLedger:
    def __init__(self, base_url: str, key: str, timeout: float = 90.0, transport: httpx.BaseTransport | None = None):
        self._c = httpx.Client(base_url=base_url.rstrip("/"), headers={"X-Gateway-Key": key}, timeout=timeout, transport=transport)

    def _call(self, method: str, path: str, *, allow_404: bool = False, **kw):
        try:
            r = self._c.request(method, path, **kw)
        except httpx.HTTPError as exc:
            raise LedgerError(f"Fabric gateway unreachable: {exc}") from exc
        if allow_404 and r.status_code == 404:
            return None
        if r.status_code >= 400:
            detail = ""
            try:
                detail = r.json().get("error", "")
            except ValueError:
                pass
            raise LedgerError(f"Fabric gateway error {r.status_code}: {detail}")
        return r.json()

    @staticmethod
    def _block(j: dict) -> Block:
        return Block(
            index=int(j["index"]), ts=j["ts"], kind=j["kind"], payload=j["payload"], payload_hash=j["payload_hash"],
            prev_hash=j["prev_hash"], block_hash=j["block_hash"], tx_id=j["tx_id"],
        )

    def anchor(self, kind: str, payload: dict) -> Block:
        payload_json = canonical(payload)
        block = self._block(self._call("POST", "/anchor", json={"kind": kind, "payload_json": payload_json}))
        if block.payload_hash != sha256_hex(payload_json):
            raise LedgerError("ledger returned a different payload hash than the one submitted")
        return block

    def get_by_tx(self, tx_id: str) -> Block | None:
        j = self._call("GET", f"/tx/{tx_id}", allow_404=True)
        return self._block(j) if j else None

    def latest(self, kind: str, scope: str | None = None) -> Block | None:
        j = self._call("GET", f"/latest/{kind}", allow_404=True, params={"scope": scope} if scope else None)
        return self._block(j) if j else None

    def verify_record(self, b: Block) -> bool:
        """The stored hash must match the payload as returned (guards against a doctored gateway response);
        the payload itself is authenticated by the endorsed transaction it came from."""
        return b.payload_hash == sha256_hex(canonical(b.payload)) and bool(b.tx_id)

    def blocks(self, offset: int = 0, limit: int = 50, kind: str | None = None) -> tuple[list[Block], int]:
        params = {"offset": offset, "limit": limit, **({"kind": kind} if kind else {})}
        j = self._call("GET", "/blocks", params=params)
        return [self._block(x) for x in j["items"]], int(j["total"])

    def verify_chain(self) -> dict:
        """Walks every block, recomputing header hashes and data hashes (done inside the gateway from the
        raw blocks fetched from the peer)."""
        return self._call("GET", "/verify")

    def status(self) -> dict:
        return self._call("GET", "/status")
