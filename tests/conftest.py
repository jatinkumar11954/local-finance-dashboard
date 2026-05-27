from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.bootstrap import bootstrap_application
from app.config import reload_settings
from app.database import get_session_factory, reset_database_state


@pytest.fixture()
def db_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    data_dir = tmp_path / "data"
    db_path = data_dir / "local_db" / "test.db"

    monkeypatch.setenv("LFI_DATA_DIR", str(data_dir))
    monkeypatch.setenv("LFI_DB_PATH", str(db_path))

    reload_settings()
    reset_database_state()
    bootstrap_application()

    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()
        reset_database_state()
        reload_settings()
