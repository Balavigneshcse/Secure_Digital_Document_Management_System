"""ClamAV (clamd) scanning over the INSTREAM protocol. No third-party dependency; enabled by SDMS_CLAMAV_HOST."""
from __future__ import annotations

import socket
import struct


class ScanError(Exception):
    """The scanner could not give a verdict (unreachable, timed out, or replied with an error)."""


class ClamAV:
    def __init__(self, host: str, port: int = 3310, timeout: float = 60.0):
        self.host, self.port, self.timeout = host, port, timeout

    def scan(self, data: bytes) -> str | None:
        """None when clean, otherwise the signature name. Raises ScanError if there is no verdict."""
        try:
            with socket.create_connection((self.host, self.port), self.timeout) as s:
                s.settimeout(self.timeout)
                s.sendall(b"zINSTREAM\0")
                for i in range(0, len(data), 65536):
                    chunk = data[i : i + 65536]
                    s.sendall(struct.pack("!I", len(chunk)) + chunk)
                s.sendall(struct.pack("!I", 0))
                reply = b""
                while not reply.endswith(b"\0") and len(reply) < 4096:
                    part = s.recv(1024)
                    if not part:
                        break
                    reply += part
        except OSError as exc:
            raise ScanError(f"scanner unreachable: {exc}") from exc
        text = reply.rstrip(b"\0\n").decode("utf-8", "replace")
        if text.endswith("OK"):
            return None
        if text.endswith("FOUND"):
            return text.split(":", 1)[-1].rsplit(" FOUND", 1)[0].strip() or "unknown"
        raise ScanError(f"scanner error: {text[:120] or 'empty reply'}")
