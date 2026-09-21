"""Application configuration."""
import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

load_dotenv(BASE_DIR.parent / ".env")
load_dotenv(BASE_DIR / ".env")


class Settings:
    def __init__(self):
        self.APP_ENV: str = os.getenv("APP_ENV", "development").strip().lower()
        # PostgreSQL is the target system of record. Keep SQLite fallback only for the temporary migration period.
        self.DATABASE_URL: str = os.getenv(
            "DATABASE_URL",
            "postgresql+psycopg://crime_analysis:crime_analysis@localhost:5432/crime_analysis",
        )
        configured_jwt_secret = os.getenv("JWT_SECRET", "").strip()
        default_jwt_secret = "crime-analysis-dev-secret-change-me-32bytes-minimum"

        if self.APP_ENV in {"production", "prod"}:
            if not configured_jwt_secret or configured_jwt_secret == default_jwt_secret:
                raise RuntimeError(
                    "JWT_SECRET must be explicitly configured with a strong random value "
                    "when APP_ENV=production."
                )
            if len(configured_jwt_secret) < 32:
                raise RuntimeError("JWT_SECRET must be at least 32 characters in production.")

        self.JWT_SECRET: str = configured_jwt_secret or default_jwt_secret
        self.JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")
        self.JWT_EXPIRE_MINUTES: int = int(os.getenv("JWT_EXPIRE_MINUTES", "720"))
        self.CORS_ORIGINS: list[str] = [
            origin.strip()
            for origin in os.getenv(
                "CORS_ORIGINS",
                "http://localhost:5173,http://127.0.0.1:5173",
            ).split(",")
            if origin.strip()
        ]
        self.LOGIN_RATE_LIMIT_ATTEMPTS: int = int(os.getenv("LOGIN_RATE_LIMIT_ATTEMPTS", "5"))
        self.LOGIN_RATE_LIMIT_WINDOW_SECONDS: int = int(
            os.getenv("LOGIN_RATE_LIMIT_WINDOW_SECONDS", "900")
        )

        self.NEO4J_URI: str = os.getenv("NEO4J_URI", "")
        self.NEO4J_USERNAME: str = os.getenv("NEO4J_USERNAME", "")
        self.NEO4J_PASSWORD: str = os.getenv("NEO4J_PASSWORD", "")

        self.NVIDIA_API_KEY: str = os.getenv("NVIDIA_API_KEY", "")
        self.NVIDIA_BASE_URL: str = os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")
        self.NVIDIA_MODEL: str = os.getenv("NVIDIA_MODEL", "nvidia/nemotron-3.5-lightning-30b-a3b")
        self.NVIDIA_TEMPERATURE: float = float(os.getenv("NVIDIA_TEMPERATURE", "0.3"))
        self.NVIDIA_TOP_P: float = float(os.getenv("NVIDIA_TOP_P", "0.95"))
        self.NVIDIA_MAX_TOKENS: int = int(os.getenv("NVIDIA_MAX_TOKENS", "1024"))
        self.NVIDIA_ENABLE_THINKING: bool = os.getenv("NVIDIA_ENABLE_THINKING", "0") == "1"
        self.NVIDIA_REASONING_BUDGET: int = int(os.getenv("NVIDIA_REASONING_BUDGET", "1024"))
        self.NVIDIA_TIMEOUT_SECONDS: float = float(os.getenv("NVIDIA_TIMEOUT_SECONDS", "300"))

        self.TESSERACT_CMD: str = os.getenv("TESSERACT_CMD", "tesseract")
        self.MAX_UPLOAD_MB: int = int(os.getenv("MAX_UPLOAD_MB", "25"))
        self.AUTO_SEED: bool = os.getenv("AUTO_SEED", "1") == "1"


settings = Settings()
