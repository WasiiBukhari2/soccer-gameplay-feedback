"""Application configuration, loaded from environment / .env."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Project root: two levels up from this file (app/config.py -> app/ -> repo root)
BASE_DIR = Path(__file__).resolve().parent.parent

# --- Anthropic ---
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
# Model is intentionally hardcoded, not env-configurable.
ANTHROPIC_MODEL = "claude-opus-4-8"

# --- Frame sampling / cost controls ---
MAX_FRAMES = int(os.getenv("MAX_FRAMES", "20"))
SAMPLE_INTERVAL_SEC = float(os.getenv("SAMPLE_INTERVAL_SEC", "1"))
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "100"))

# --- CORS ---
_raw_origins = os.getenv("ALLOWED_ORIGINS", "*")
ALLOWED_ORIGINS = [o.strip() for o in _raw_origins.split(",") if o.strip()] or ["*"]

# --- Filesystem ---
UPLOADS_DIR = BASE_DIR / "uploads"

# --- Uploads ---
ALLOWED_VIDEO_CONTENT_TYPES = {
    "video/mp4",
    "video/quicktime",
    "video/x-msvideo",
}
