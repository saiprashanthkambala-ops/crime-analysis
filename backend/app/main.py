from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import settings, BASE_DIR
from .database import Base, engine, ensure_column_migrations
from .routers import auth, data, intelligence, admin
from .seed import run_seed
from .services.neo4j_service import close_driver, init_neo4j, neo4j_status


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    ensure_column_migrations()
    if settings.AUTO_SEED:
        run_seed()
    # Remote Neo4j (Phase 1: connectivity only). Never fatal — SQLite and all
    # existing APIs keep working when Neo4j is missing or unreachable.
    init_neo4j()
    yield
    close_driver()


app = FastAPI(title="Crime Analysis API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(data.router)
app.include_router(intelligence.router)
app.include_router(admin.router)


@app.get("/health")
def health():
    """Basic application health, kept compatible with the original contract.

    ``status`` stays ``"healthy"`` as long as the API itself is up — Neo4j
    problems are reported separately under ``neo4j`` and never mark the whole
    application unhealthy.
    """
    return {"status": "healthy", "neo4j": neo4j_status()}


@app.get("/api/health/neo4j")
def neo4j_health():
    """Dedicated Neo4j diagnostic.

    Executes a real ``RETURN 1`` Cypher query against the remote database and
    returns 503 when Neo4j is configured but unreachable. The response never
    contains credentials or the connection URI.
    """
    status = neo4j_status()
    http_status = 503 if status["status"] == "unavailable" else 200
    return JSONResponse(status_code=http_status, content=status)


# ---------------------------------------------------------------- static SPA
# Registered last so API routes always take precedence over the SPA fallback.
FRONTEND_DIST = BASE_DIR.parent / "frontend" / "dist"

if FRONTEND_DIST.exists() and (FRONTEND_DIST / "assets").exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")


@app.get("/{full_path:path}", include_in_schema=False)
def spa_fallback(full_path: str):
    # Unknown API routes must 404 (JSON), never return the SPA.
    if full_path == "api" or full_path.startswith("api/"):
        return JSONResponse({"detail": "Not found"}, status_code=404)
    if FRONTEND_DIST.exists():
        candidate = FRONTEND_DIST / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(FRONTEND_DIST / "index.html")
    return {"detail": "Frontend build not found. Run `npm run build` in frontend/."}
