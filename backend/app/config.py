"""Runtime configuration. All values can be overridden with SDMS_* environment variables (or backend/.env)."""
from __future__ import annotations

import base64
import os
import secrets
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SDMS_", env_file=".env", extra="ignore")

    # --- data stores (PostgreSQL = structured/case data + audit log, MongoDB = document metadata + encrypted blobs)
    database_url: str = ""  # postgresql+psycopg://user:pass@host:5432/dbname   (required)
    mongo_url: str = ""  # mongodb://host:27017                                   (required)
    mongo_db: str = "sdms"

    # Only used for generated dev secrets (jwt.secret / master.key) when they are not supplied via env.
    data_dir: Path = Path("data")

    # Secrets. If unset they are generated once and persisted under data_dir (dev only).
    # In production the master key belongs in a KMS/HSM, not on the application disk.
    jwt_secret: str | None = None
    master_key: str | None = None  # base64-encoded 32 bytes

    access_token_minutes: int = 30
    mfa_token_minutes: int = 5
    lockout_threshold: int = 5
    lockout_minutes: int = 15
    totp_issuer: str = "SDMS"

    max_upload_mb: int = 25

    # --- abuse protection
    rate_limit_enabled: bool = True
    login_attempts_per_minute: int = 10  # per client IP (per-account lockout is separate)
    upload_per_minute: int = 30  # per user
    trusted_proxies: str = ""  # comma-separated IPs/CIDRs of reverse proxies whose X-Forwarded-For is believed
    # How many trusted proxies append to X-Forwarded-For. 0 = walk the header skipping trusted addresses (for when
    # trusted_proxies lists only proxies); N > 0 = the client is the Nth entry from the right, whatever its address -
    # needed when clients share the proxies' private ranges (a LAN deployment behind nginx).
    trusted_proxy_hops: int = 0
    session_max_hours: int = 8  # absolute cap on a login session, however often it is refreshed

    # --- optional antivirus (ClamAV clamd). Unset host = scanning off.
    clamav_host: str | None = None
    clamav_port: int = 3310
    clamav_required: bool = False  # true: refuse uploads while the scanner is unreachable
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # --- integrity ledger: "fabric" (Hyperledger Fabric via the gateway service) or "memory" (tests only)
    ledger_backend: str = "fabric"
    fabric_gateway_url: str = "http://127.0.0.1:8088"
    fabric_gateway_key: str | None = None

    # --- AI: unset ai_service_url = built-in rule-based stub (no embeddings / no OCR of scans)
    ai_service_url: str | None = None
    # Shared secret for the AI contract. Required when ai_service_url is set; also enables the
    # reference /ai/* endpoints served by this app. No default: those endpoints stay off unless configured.
    ai_service_key: str | None = None
    ai_timeout_seconds: float = 120.0

    enable_docs: bool = False  # Swagger UI / OpenAPI at /docs; leave off outside development
    seed_demo: bool = False
    audit_anchor_interval_seconds: int = 300  # 0 disables the periodic audit-head anchor

    @model_validator(mode="after")
    def _require_stores(self):
        if not self.database_url.startswith("postgresql"):
            raise ValueError("SDMS_DATABASE_URL must be a PostgreSQL URL, e.g. postgresql+psycopg://user:pass@localhost:5432/sdms")
        if not self.mongo_url.startswith("mongodb"):
            raise ValueError("SDMS_MONGO_URL must be a MongoDB URL, e.g. mongodb://localhost:27017")
        if self.ledger_backend not in ("fabric", "memory"):
            raise ValueError("SDMS_LEDGER_BACKEND must be 'fabric' or 'memory'")
        if self.ledger_backend == "fabric" and not self.fabric_gateway_key:
            raise ValueError("SDMS_FABRIC_GATEWAY_KEY is required with the fabric ledger")
        return self

    @property
    def trusted_proxy_list(self) -> list[str]:
        return [p.strip() for p in self.trusted_proxies.split(",") if p.strip()]

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def _persisted_secret(self, name: str, nbytes: int) -> bytes:
        path = self.data_dir / name
        if path.exists():
            return base64.b64decode(path.read_text().strip())
        self.data_dir.mkdir(parents=True, exist_ok=True)
        raw = secrets.token_bytes(nbytes)
        path.write_text(base64.b64encode(raw).decode())
        os.chmod(path, 0o600)  # the master key decrypts every document: owner-only
        return raw

    def jwt_key(self) -> str:
        if self.jwt_secret:
            return self.jwt_secret
        return base64.b64encode(self._persisted_secret("jwt.secret", 48)).decode()

    def kek(self) -> bytes:
        """Key-encryption key that wraps per-file data keys."""
        if self.master_key:
            key = base64.b64decode(self.master_key)
        else:
            key = self._persisted_secret("master.key", 32)
        if len(key) != 32:
            raise ValueError("SDMS_MASTER_KEY must decode to exactly 32 bytes")
        return key
