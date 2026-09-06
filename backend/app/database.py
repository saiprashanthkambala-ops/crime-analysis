from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

from .config import settings

connect_args = {}
if settings.DATABASE_URL.startswith("sqlite"):
    connect_args["check_same_thread"] = False

engine = create_engine(settings.DATABASE_URL, connect_args=connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Lightweight migrations
#
# ``Base.metadata.create_all`` only creates tables that do not exist yet, so an
# existing development database would silently miss columns added later. For
# SQLite we add the missing columns in place so previously created databases
# (including the seeded demo) keep working after an upgrade.
# ---------------------------------------------------------------------------
_DOCUMENT_ADDITIONS = {
    "file_size": "INTEGER DEFAULT 0",
    "sha256": "VARCHAR(64)",
    "records_processed": "INTEGER DEFAULT 0",
    "entities_discovered": "INTEGER DEFAULT 0",
    "persons_discovered": "INTEGER DEFAULT 0",
    "relationships_discovered": "INTEGER DEFAULT 0",
    "evidence_discovered": "INTEGER DEFAULT 0",
    "warnings": "JSON",
    "mapping": "JSON",
    "detected_columns": "JSON",
    "retry_count": "INTEGER DEFAULT 0",
}


def ensure_column_migrations():
    """Add columns introduced after the first public release, if missing."""
    if not settings.DATABASE_URL.startswith("sqlite"):
        # Other backends should be migrated via the framework of choice.
        return
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    if not tables:
        return
    with engine.begin() as conn:
        if "documents" in tables:
            existing = {c["name"] for c in inspector.get_columns("documents")}
            for name, ddl in _DOCUMENT_ADDITIONS.items():
                if name not in existing:
                    conn.execute(text(f"ALTER TABLE documents ADD COLUMN {name} {ddl}"))
        # refresh inspector state after ALTER statements
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
    return None
