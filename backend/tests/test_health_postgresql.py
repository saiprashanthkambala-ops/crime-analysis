import os

from sqlalchemy import create_engine, text


def test_postgresql_driver_is_supported():
    url = os.getenv(
        "POSTGRES_TEST_URL",
        "postgresql+psycopg://crime_analysis:crime_analysis@localhost:5432/crime_analysis",
    )
    engine = create_engine(url, future=True)
    assert engine.url.drivername == "postgresql+psycopg"


def test_postgresql_connection_round_trip_when_configured():
    url = os.getenv("POSTGRES_TEST_URL")
    if not url:
        return
    engine = create_engine(url, future=True, pool_pre_ping=True)
    with engine.connect() as conn:
        assert conn.execute(text("SELECT 1")).scalar_one() == 1
