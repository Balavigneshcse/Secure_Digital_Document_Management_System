"""Client IP resolution and rate limiting.

Behind a reverse proxy (nginx) the TCP peer is always the proxy, so without care every user shares one IP: the audit log
loses meaning and one user's failed logins would lock everyone out of a per-IP limiter. `X-Forwarded-For` is honoured only
when the direct peer is a configured trusted proxy, and it is read right-to-left, skipping trusted hops, so a client
cannot spoof its address by sending its own header.
"""
from __future__ import annotations

import ipaddress
import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request


def _trusted(host: str, trusted: list[str]) -> bool:
    for t in trusted:
        if host == t:
            return True
        try:
            if ipaddress.ip_address(host) in ipaddress.ip_network(t, strict=False):
                return True
        except ValueError:
            continue
    return False


def resolve_ip(request: Request) -> str | None:
    if not request.client:
        return None
    peer = request.client.host
    trusted = request.app.state.settings.trusted_proxy_list
    xff = request.headers.get("x-forwarded-for")
    if not trusted or not xff or not _trusted(peer, trusted):
        return peer
    for hop in reversed([h.strip() for h in xff.split(",") if h.strip()]):
        if not _trusted(hop, trusted):
            return hop[:64]
    return peer


class SlidingWindow:
    """In-process sliding-window counter. Correct for one API instance; with several, use a shared store (e.g. Redis)."""

    def __init__(self):
        self._hits: dict[tuple, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def hit(self, key: tuple, limit: int, window_s: float) -> tuple[bool, int, bool]:
        """Records a request. Returns (allowed, retry_after_seconds, is_first_violation_in_window)."""
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] > window_s:
                q.popleft()
            if len(q) >= limit:
                first = len(q) == limit  # only the first refusal is worth an audit entry (no log flooding)
                q.append(now) if first else None
                return False, max(1, int(window_s - (now - q[0])) + 1), first
            q.append(now)
            if len(self._hits) > 50_000:  # bound memory: drop idle keys
                for k in [k for k, v in self._hits.items() if not v or now - v[-1] > window_s]:
                    self._hits.pop(k, None)
            return True, 0, False


limiter = SlidingWindow()


class RateLimited(HTTPException):
    def __init__(self, retry_after: int, first: bool):
        super().__init__(429, "Too many requests. Please wait and try again.", headers={"Retry-After": str(retry_after)})
        self.first = first  # True for the first refusal in a window (the only one worth an audit entry)


def enforce(request: Request, bucket: str, limit: int, window_s: float = 60.0, *, key: str | None = None) -> None:
    """Raises RateLimited (HTTP 429) when `bucket` is exhausted for this client (or `key`)."""
    if not request.app.state.settings.rate_limit_enabled:
        return
    allowed, retry, first = limiter.hit((bucket, key or resolve_ip(request) or "?"), limit, window_s)
    if not allowed:
        raise RateLimited(retry, first)
