from __future__ import annotations

from pathlib import Path
import sys

import streamlit as st

DASHBOARD_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = DASHBOARD_DIR.parent
for path in (PROJECT_ROOT, DASHBOARD_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from app.config import get_settings
from common import initialize_page, render_reset_controls, render_sidebar_status


initialize_page("Settings")
render_sidebar_status()

settings = get_settings()

st.title("Settings")
st.caption("Security and local storage controls.")

st.write(f"Project root: `{settings.project_root}`")
st.write(f"Database path: `{settings.database_path}`")
st.write(f"Uploads folder: `{settings.uploads_dir}`")
st.write(f"Processed folder: `{settings.processed_dir}`")
st.write(f"Benchmark seed file: `{settings.benchmark_seed_file}`")
st.write(f"Password protection enabled: `{bool(settings.app_password_hash)}`")
st.write(f"Local embedding model: `{settings.local_embedding_model_path or 'not configured'}`")
st.write(f"Local LLM provider: `{settings.local_llm_provider or 'not configured'}`")
st.write(f"Ollama model: `{settings.ollama_model}`")
st.write(f"Ollama URL: `{settings.ollama_base_url}`")

render_reset_controls()
