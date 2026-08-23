"""FastAPI application entrypoint."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app import config
from app.routers.analyze import router as analyze_router

app = FastAPI(title="Soccer Gameplay Feedback")

# The frontend may be deployed separately from the backend (e.g. Netlify
# frontend + Render backend), so CORS is required.
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(analyze_router)

# Ensure the uploads dir exists for streaming writes.
config.UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

_STATIC_DIR = config.BASE_DIR / "static"
app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(_STATIC_DIR / "index.html")
