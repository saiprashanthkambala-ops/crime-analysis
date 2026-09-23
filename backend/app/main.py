from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import text
from fastapi.staticfiles import StaticFiles

from .config import BASE_DIR, settings
from .database import Base, engine
from .routers import auth, data, intelligence, admin, graph, analysis, graph_analysis
from .seed import run_seed
from .services.neo4j_service import close_driver, init_neo4j, neo4j_status
from .neo4j.schema import initialize_schema


def _ensure_sql_indexes(bind_engine):
    """Safely and idempotently ensure performance indexes exist on existing relational tables."""
    statements = [
        "CREATE INDEX IF NOT EXISTS ix_documents_case_id ON documents (case_id)",
        "CREATE INDEX IF NOT EXISTS ix_entities_case_id ON entities (case_id)",
        "CREATE INDEX IF NOT EXISTS ix_events_case_id ON events (case_id)",
        "CREATE INDEX IF NOT EXISTS ix_events_person_a_id ON events (person_a_id)",
        "CREATE INDEX IF NOT EXISTS ix_events_person_b_id ON events (person_b_id)",
        "CREATE INDEX IF NOT EXISTS ix_evidence_case_id ON evidence (case_id)",
        "CREATE INDEX IF NOT EXISTS ix_evidence_person_a_id ON evidence (person_a_id)",
        "CREATE INDEX IF NOT EXISTS ix_evidence_person_b_id ON evidence (person_b_id)",
        "CREATE INDEX IF NOT EXISTS ix_relationships_score ON relationships (score)",
        "CREATE INDEX IF NOT EXISTS ix_relationships_person_a_b ON relationships (person_a_id, person_b_id)",
    ]
    try:
        with bind_engine.connect() as conn:
            for stmt in statements:
                try:
                    conn.execute(text(stmt))
                except Exception:
                    pass
            conn.commit()
    except Exception:
        pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    _ensure_sql_indexes(engine)
    if settings.AUTO_SEED:
        run_seed()
    try:
        init_neo4j()
    except Exception as exc:  # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning("Neo4j startup check failed: %s", exc)
    try:
        if neo4j_status().get("connected"):
            try:
                initialize_schema()
            except Exception as exc:  # noqa: BLE001
                import logging
                logging.getLogger(__name__).warning("Neo4j schema initialization failed: %s", exc)
    except Exception as exc:  # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning("Neo4j status check failed: %s", exc)
    yield
    try:
        close_driver()
    except Exception:
        pass


app = FastAPI(title="Crime Analysis API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(data.router)
app.include_router(intelligence.router)
app.include_router(admin.router)
app.include_router(graph.router)
app.include_router(analysis.router)
app.include_router(graph_analysis.router)


import threading
import time

_cached_neo4j = {"data": None, "expires_at": 0.0}
_cached_neo4j_lock = threading.Lock()


def get_cached_neo4j_status(ttl_seconds: float = 30.0) -> dict:
    from .services import neo4j_service
    key = (
        settings.NEO4J_URI,
        settings.NEO4J_USERNAME,
        settings.NEO4J_PASSWORD,
        id(getattr(neo4j_service, "_driver", None)),
    )
    now = time.monotonic()
    with _cached_neo4j_lock:
        if (
            _cached_neo4j["data"] is not None
            and _cached_neo4j.get("key") == key
            and now < _cached_neo4j["expires_at"]
        ):
            return _cached_neo4j["data"]
        status = neo4j_status()
        _cached_neo4j["data"] = status
        _cached_neo4j["key"] = key
        _cached_neo4j["expires_at"] = now + ttl_seconds
        return status


@app.get("/health")
def health():
    return {"status": "healthy", "neo4j": get_cached_neo4j_status()}


@app.get("/api/health/database")
def database_health():
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"connected": True, "status": "connected", "database": "postgresql"}
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            status_code=503,
            content={"connected": False, "status": "unavailable", "database": "postgresql", "detail": str(exc)},
        )


@app.get("/api/health/neo4j")
def neo4j_health():
    status = neo4j_status()
    return JSONResponse(status_code=503 if status["status"] == "unavailable" else 200, content=status)


@app.get("/api/neo4j/status")
@app.get("/api/neo4j/connected")
def neo4j_status_endpoint():
    return JSONResponse(status_code=200, content=neo4j_status())


FRONTEND_DIST = BASE_DIR.parent / "frontend" / "dist"

if FRONTEND_DIST.exists() and (FRONTEND_DIST / "assets").exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")


@app.get("/{full_path:path}", include_in_schema=False)
def spa_fallback(full_path: str):
    if full_path == "api" or full_path.startswith("api/"):
        return JSONResponse({"detail": "Not found"}, status_code=404)
    if FRONTEND_DIST.exists():
        candidate = FRONTEND_DIST / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(FRONTEND_DIST / "index.html")
    return {"detail": "Frontend build not found. Run npm run build in frontend/."}
