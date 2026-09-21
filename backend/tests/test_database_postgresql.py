import os

from sqlalchemy import create_engine, inspect


def test_postgresql_url_supported():
    url = os.getenv("DATABASE_URL", "postgresql+psycopg://crime_analysis:crime_analysis@localhost:5432/crime_analysis")
    assert url.startswith("postgresql+psycopg://")


def test_models_can_compile_for_postgresql():
    from app.database import Base
    from app.models import (  # noqa: F401
        AuditLog, Case, Document, Entity, Event, Evidence, Feedback,
        Person, ProcessingJob, Relationship, User,
    )

    engine = create_engine(
        "postgresql+psycopg://user:password@localhost:5432/example",
        future=True,
    )
    assert "users" in Base.metadata.tables
    assert "cases" in Base.metadata.tables
    assert "documents" in Base.metadata.tables
    assert "relationships" in Base.metadata.tables
    assert "audit_logs" in Base.metadata.tables
    # Compilation/inspection of metadata does not require a live database.
    assert str(Base.metadata.tables["cases"].c.neo4j_sync_counts.type.compile(dialect=engine.dialect)) == "JSON"
