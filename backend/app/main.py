from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from . import audit
from .ai.http_client import HttpAI
from .ai.stub import StubAI
from .antivirus import ClamAV
from .config import Settings
from .db import Base, advisory_xact_lock, make_engine, make_session_factory
from .ledger import MemoryLedger
from .mongo import Mongo
from .routers import audit_api, auth, cases, documents, ledger_api, search, users
from .models import SystemMeta
from .seed import seed_demo
from .storage import GridFSStorage

log = logging.getLogger("sdms")


def _anchor_once(app: FastAPI) -> None:
    with app.state.session_factory() as db:
        audit.anchor_head(db, app.state.ledger, app.state.chain_id)


async def _anchor_loop(app: FastAPI, interval: int) -> None:
    while True:
        await asyncio.sleep(interval)
        try:
            await asyncio.to_thread(_anchor_once, app)
        except Exception:  # keep the loop alive; a failed anchor is retried next tick
            log.exception("periodic audit anchor failed")


def _chain_id(session_factory) -> str:
    """Identifies this deployment's audit chain on the (possibly shared) ledger. Created once, then stable."""
    with session_factory() as db:
        advisory_xact_lock(db, "sdms-chain-id")
        row = db.get(SystemMeta, "audit_chain_id")
        if row is None:
            row = SystemMeta(key="audit_chain_id", value=uuid.uuid4().hex)
            db.add(row)
            db.commit()
        return row.value


def _make_ledger(settings: Settings):
    if settings.ledger_backend == "memory":
        log.warning("SDMS_LEDGER_BACKEND=memory: the ledger is NOT durable. Use Hyperledger Fabric outside tests.")
        return MemoryLedger()
    from .fabric_ledger import FabricLedger  # imported lazily: only needed with a Fabric network

    return FabricLedger(settings.fabric_gateway_url, settings.fabric_gateway_key or "")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        task = None
        if settings.audit_anchor_interval_seconds > 0:
            task = asyncio.create_task(_anchor_loop(app, settings.audit_anchor_interval_seconds))
        yield
        if task:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        app.state.mongo.close()
        app.state.engine.dispose()

    if settings.ai_service_url and not settings.ai_service_key:
        raise ValueError("SDMS_AI_SERVICE_KEY is required when SDMS_AI_SERVICE_URL is set")

    docs = {} if settings.enable_docs else {"docs_url": None, "redoc_url": None, "openapi_url": None}
    app = FastAPI(title="Secure Digital Document Management System", version="0.2.0", lifespan=lifespan, **docs)

    engine = make_engine(settings.database_url)
    Base.metadata.create_all(engine)
    session_factory = make_session_factory(engine)
    mongo = Mongo(settings.mongo_url, settings.mongo_db)
    mongo.ensure_indexes()
    if settings.seed_demo:
        with session_factory() as db:
            seed_demo(db)

    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.mongo = mongo
    app.state.chain_id = _chain_id(session_factory)
    app.state.kek = settings.kek()
    app.state.storage = GridFSStorage(mongo.blobs)
    app.state.av = ClamAV(settings.clamav_host, settings.clamav_port) if settings.clamav_host else None
    app.state.ledger = _make_ledger(settings)
    app.state.ai = (
        HttpAI(settings.ai_service_url, settings.ai_service_key, settings.ai_timeout_seconds)
        if settings.ai_service_url
        else StubAI()
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
        expose_headers=["Content-Disposition", "X-Content-SHA256"],
    )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        resp = await call_next(request)
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "no-referrer")
        if request.url.path.startswith("/api"):
            resp.headers.setdefault("Cache-Control", "no-store")
            resp.headers.setdefault("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
        return resp

    for r in (auth.router, users.router, cases.router, documents.router, search.router, audit_api.router, ledger_api.router):
        app.include_router(r)

    @app.get("/api/health", tags=["meta"])
    def health():
        # Public: reveals only whether things are up. Channel/peer/height details are auditor-only (/api/ledger/status).
        out = {"status": "ok", "ai": getattr(app.state.ai, "name", "external")}
        try:
            app.state.ledger.status()
            out["ledger"] = {"backend": settings.ledger_backend, "reachable": True}
        except Exception:  # the health probe must not fail because the ledger is down
            out["status"], out["ledger"] = "degraded", {"backend": settings.ledger_backend, "reachable": False}
        return out

    return app
