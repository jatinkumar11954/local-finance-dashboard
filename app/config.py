from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Settings:
    project_name: str
    project_root: Path
    data_dir: Path
    uploads_dir: Path
    processed_dir: Path
    local_db_dir: Path
    database_path: Path
    database_url: str
    benchmark_seed_file: Path
    default_benchmark_city: str
    default_benchmark_profile: str
    app_password_hash: str | None
    local_embedding_model_path: Path | None
    local_llm_provider: str | None
    ollama_base_url: str
    ollama_model: str


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    data_dir = Path(os.getenv("LFI_DATA_DIR", PROJECT_ROOT / "data")).resolve()
    uploads_dir = data_dir / "uploads"
    processed_dir = data_dir / "processed"
    local_db_dir = data_dir / "local_db"
    default_db_path = local_db_dir / "finance_dashboard.db"
    database_path = Path(os.getenv("LFI_DB_PATH", default_db_path)).resolve()
    database_url = f"sqlite:///{database_path}"

    app_password_hash = os.getenv("LFI_APP_PASSWORD_HASH")
    raw_password = os.getenv("LFI_APP_PASSWORD")
    if not app_password_hash and raw_password:
        from app.utils.security import hash_password

        app_password_hash = hash_password(raw_password)
    local_embedding_model_path = os.getenv("LFI_LOCAL_EMBEDDING_MODEL_PATH")
    local_llm_provider = os.getenv("LFI_LOCAL_LLM_PROVIDER")

    return Settings(
        project_name="Local Finance Intelligence Dashboard",
        project_root=PROJECT_ROOT,
        data_dir=data_dir,
        uploads_dir=uploads_dir,
        processed_dir=processed_dir,
        local_db_dir=local_db_dir,
        database_path=database_path,
        database_url=database_url,
        benchmark_seed_file=PROJECT_ROOT / "data" / "benchmarks" / "hyderabad_benchmarks.json",
        default_benchmark_city="Hyderabad",
        default_benchmark_profile="Comfortable living",
        app_password_hash=app_password_hash,
        local_embedding_model_path=Path(local_embedding_model_path).expanduser().resolve()
        if local_embedding_model_path
        else None,
        local_llm_provider=local_llm_provider.lower() if local_llm_provider else None,
        ollama_base_url=os.getenv("LFI_OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/"),
        ollama_model=os.getenv("LFI_OLLAMA_MODEL", "qwen2.5:7b-instruct"),
    )


def reload_settings() -> None:
    get_settings.cache_clear()
