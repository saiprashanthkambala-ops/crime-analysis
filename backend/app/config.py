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
        self.DATABASE_URL: str = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'crime_analysis.db'}")
        self.JWT_SECRET: str = os.getenv("JWT_SECRET", "crime-analysis-dev-secret-change-me-32bytes-minimum")
        self.JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")
        self.JWT_EXPIRE_MINUTES: int = int(os.getenv("JWT_EXPIRE_MINUTES", "720"))

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
        self.NVIDIA_TIMEOUT_SECONDS: float = float(os.getenv("NVIDIA_TIMEOUT_SECONDS", "120"))

        self.TESSERACT_CMD: str = os.getenv("TESSERACT_CMD", "tesseract")
        self.MAX_UPLOAD_MB: int = int(os.getenv("MAX_UPLOAD_MB", "25"))
        self.AUTO_SEED: bool = os.getenv("AUTO_SEED", "1") == "1"

settings = Settings()
