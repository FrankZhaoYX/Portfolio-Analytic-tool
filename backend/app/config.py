from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    eodhd_api_key: str = ""
    db_service_host: str = "localhost:8080"
    db_service_imports_dir: str = str(REPO_ROOT / "db-service" / "data" / "imports")
    benchmark_symbol: str = "GSPC.INDX"
    risk_free_rate: float = 0.0

    # DEBUG surfaces per-symbol fetches and query timings; INFO is the default.
    log_level: str = "INFO"
    log_dir: str = str(REPO_ROOT / "logs")

    model_config = SettingsConfigDict(env_file=str(REPO_ROOT / ".env"), env_file_encoding="utf-8")


settings = Settings()
