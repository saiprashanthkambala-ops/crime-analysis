"""Application configuration.

All secrets / connection strings come from environment variables so that the
MongoDB / Neo4j backing stores can be swapped in without code changes. The
default development profile uses SQLite and an in-process graph layer so the
whole system runs without external services.

For local development a ``.env`` file (repo root or ``backend/``) is loaded
for convenience; real environment variables always take precedence over
``.env`` values, so production deployments configure everything through the
environment. See docs/ENVIRONMENT.md — the ``.env`` file must never be
committed.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent  # backend/
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

# Optional local .env files (git-ignored). Existing environment variables are
# never overridden, so .env is a developer convenience, not a source of truth.
load_dotenv(BASE_DIR.parent / ".env")
load_dotenv(BASE_DIR / ".env")


class Settings:
    """Runtime settings, read from the environment when instantiated."""

    def __init__(self):
        # SQLAlchemy URL. Defaults to SQLite (JSON columns emulate the flexible
        # Mongo-style documents described in the PRD). SQLite stays the
        # application's system of record.
        self.DATABASE_URL: str = os.getenv(
            "DATABASE_URL", f"sqlite:///{BASE_DIR / 'crime_analysis.db'}"
        )

        # Auth
        self.JWT_SECRET: str = os.getenv(
            "JWT_SECRET", "crime-analysis-dev-secret-change-me-32bytes-minimum"
        )
        self.JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")
        self.JWT_EXPIRE_MINUTES: int = int(os.getenv("JWT_EXPIRE_MINUTES", "720"))

        # Remote Neo4j graph database (Phase 1: connectivity only). All three
        # values must be set to enable the connection — the empty defaults
        # intentionally disable the feature instead of guessing credentials.
        # See docs/ENVIRONMENT.md.
        self.NEO4J_URI: str = os.getenv("NEO4J_URI", "")
        self.NEO4J_USERNAME: str = os.getenv("NEO4J_USERNAME", "")
        self.NEO4J_PASSWORD: str = os.getenv("NEO4J_PASSWORD", "")

        # OCR (Tesseract / PaddleOCR). When TESSERACT_CMD is unavailable the
        # pipeline falls back to direct text extraction and flags the document.
        self.TESSERACT_CMD: str = os.getenv("TESSERACT_CMD", "tesseract")

        # Dataset import limits. Individual uploaded files larger than this are
        # rejected during validation (investigators can split large exports).
        self.MAX_UPLOAD_MB: int = int(os.getenv("MAX_UPLOAD_MB", "25"))

        # Seed the synthetic demo dataset on startup when the DB is empty.
        self.AUTO_SEED: bool = os.getenv("AUTO_SEED", "1") == "1"


settings = Settings()
