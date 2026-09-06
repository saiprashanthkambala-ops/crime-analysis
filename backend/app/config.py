"""Application configuration.

All secrets / connection strings come from environment variables so that the
MongoDB / Neo4j backing stores can be swapped in without code changes. The
default development profile uses SQLite and an in-process graph layer so the
whole system runs without external services.
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent  # backend/
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)


class Settings:
    # SQLAlchemy URL. Defaults to SQLite (JSON columns emulate the flexible
    # Mongo-style documents described in the PRD).
    DATABASE_URL: str = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'crimelink.db'}")

    # Auth
    JWT_SECRET: str = os.getenv("JWT_SECRET", "crimelink-dev-secret-change-me-32bytes-minimum")
    JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")
    JWT_EXPIRE_MINUTES: int = int(os.getenv("JWT_EXPIRE_MINUTES", "720"))

    # Graph store (Neo4j when provided; the in-process layer is used otherwise)
    NEO4J_URI: str = os.getenv("NEO4J_URI", "")
    NEO4J_USERNAME: str = os.getenv("NEO4J_USERNAME", "neo4j")
    NEO4J_PASSWORD: str = os.getenv("NEO4J_PASSWORD", "")

    # OCR (Tesseract / PaddleOCR). When TESSERACT_CMD is unavailable the
    # pipeline falls back to direct text extraction and flags the document.
    TESSERACT_CMD: str = os.getenv("TESSERACT_CMD", "tesseract")

    # Seed the synthetic demo dataset on startup when the DB is empty.
    AUTO_SEED: bool = os.getenv("AUTO_SEED", "1") == "1"


settings = Settings()
