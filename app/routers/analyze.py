"""POST /api/analyze — accept an upload, sample frames, return AI feedback."""
from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app import config
from app.models.schemas import FeedbackReport
from app.services.ai_analysis import AnalysisError, analyze_frames
from app.services.video_frames import VideoReadError, extract_frames

router = APIRouter()

# Map allowed content types to a file extension for the saved upload.
_EXTENSIONS = {
    "video/mp4": "mp4",
    "video/quicktime": "mov",
    "video/x-msvideo": "avi",
}

_CHUNK_SIZE = 1024 * 1024  # 1 MiB


@router.post("/api/analyze", response_model=FeedbackReport)
async def analyze(
    video: UploadFile = File(...),
    jersey_number: str = Form(...),
    jersey_color: str = Form(...),
) -> FeedbackReport:
    if video.content_type not in config.ALLOWED_VIDEO_CONTENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=(
                "Unsupported video type. Please upload an MP4, MOV, or AVI file."
            ),
        )

    ext = _EXTENSIONS.get(video.content_type, "mp4")
    request_dir = config.UPLOADS_DIR / uuid.uuid4().hex
    request_dir.mkdir(parents=True, exist_ok=True)
    video_path = request_dir / f"video.{ext}"

    max_bytes = config.MAX_UPLOAD_MB * 1024 * 1024
    written = 0

    try:
        with video_path.open("wb") as out:
            while True:
                chunk = await video.read(_CHUNK_SIZE)
                if not chunk:
                    break
                written += len(chunk)
                if written > max_bytes:
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            f"Video exceeds the maximum upload size of "
                            f"{config.MAX_UPLOAD_MB} MB."
                        ),
                    )
                out.write(chunk)

        if written == 0:
            raise HTTPException(status_code=400, detail="The uploaded file is empty.")

        frames_dir = request_dir / "frames"
        try:
            frames = extract_frames(video_path, frames_dir)
        except VideoReadError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        try:
            report = analyze_frames(frames, jersey_number, jersey_color)
        except AnalysisError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        return report
    finally:
        # Nothing persists across requests — always clean up.
        shutil.rmtree(request_dir, ignore_errors=True)
