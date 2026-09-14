from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import BASE_DIR, settings
from .database import Base, engine, ensure_column_migrations
from .routers import auth, data, intelligence, admin, graph, analysis, graph_analysis
from .seed import run_seed
from .services.neo4j_service import close_driver, init_neo4j, neo4j_status
from .neo4j.schema import initialize_schema


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    ensure_column_migrations()
    if settings.AUTO_SEED:
        run_seed()
    init_neo4j()
    if neo4j_status().get("connected"):
        try:
            initialize_schema()
        except Exception as exc:  # noqa: BLE001
            import logging
            logging.getLogger(__name__).warning("Neo4j schema initialization failed: %s", exc)
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
app.include_router(graph.router)
app.include_router(analysis.router)
app.include_router(graph_analysis.router)


@app.get("/health")
def health():
    return {"status": "healthy", "neo4j": neo4j_status()}


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
