"""Client IP resolution and rate limiting.

Behind a reverse proxy (nginx) the TCP peer is always the proxy, so without care every user shares one IP: the audit log
loses meaning and one user's failed logins would lock everyone out of a per-IP limiter. `X-Forwarded-For` is honoured only
when the direct peer is a configured trusted proxy. It is read from the right - either a fixed number of proxy hops
(`trusted_proxy_hops`, for a known topology such as nginx in front of a LAN) or skipping trusted addresses - so a client
cannot spoof its address by sending its own header. Anything that isn't a valid IP address is never recorded.
"""
from __future__ import annotations

import ipaddress
import threading
import time
from collections import OrderedDict, defaultdict, deque

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


def _is_ip(value: str) -> bool:
    if len(value) > 64:  # the audit log's ip column; an IPv6 scope id could otherwise make it arbitrarily long
        return False
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return False


def resolve_ip(request: Request) -> str | None:
    if not request.client:
        return None
    peer = request.client.host
    settings = request.app.state.settings
    trusted = settings.trusted_proxy_list
    xff = request.headers.get("x-forwarded-for")
    if not trusted or not xff or not _trusted(peer, trusted):
        return peer
    hops = [h.strip() for h in xff.split(",") if h.strip()]
    n = settings.trusted_proxy_hops
    if n > 0:
        # Each of our n proxies appended exactly one entry, so the client is n from the right. Anything further left
        # was written by the client; a chain shorter than n means a proxy was bypassed - trust neither.
        client = hops[-n] if len(hops) >= n else None
        return client if client and _is_ip(client) else peer
    for hop in reversed(hops):
        if not _trusted(hop, trusted):
            return hop if _is_ip(hop) else peer
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


class UnknownUserLockout:
    """Mirrors the per-account lockout for usernames that don't exist. Without it a real account answers 423 after
    repeated failures while a made-up one keeps answering 401 - which tells an attacker which usernames are real."""

    def __init__(self, max_entries: int = 10_000):
        self._state: OrderedDict[str, list] = OrderedDict()  # name -> [failures, locked until (monotonic)]
        self._lock = threading.Lock()
        self._max = max_entries

    def locked(self, name: str) -> bool:
        with self._lock:
            entry = self._state.get(name)
            return bool(entry and entry[1] > time.monotonic())

    def fail(self, name: str, threshold: int, minutes: int) -> None:
        with self._lock:
            entry = self._state.pop(name, None) or [0, 0.0]
            entry[0] += 1
            if entry[0] >= threshold:  # same rule as the real account: lock, reset the count
                entry[0], entry[1] = 0, time.monotonic() + minutes * 60
            self._state[name] = entry
            while len(self._state) > self._max:
                self._state.popitem(last=False)


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
