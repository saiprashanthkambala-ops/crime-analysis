from sqlalchemy import text

from app.database import engine


def test_postgresql_engine_uses_postgresql():
    assert engine.url.drivername == "postgresql+psycopg"


def test_postgresql_connection_round_trip():
    with engine.connect() as conn:
        assert conn.execute(text("SELECT 1")).scalar_one() == 1
