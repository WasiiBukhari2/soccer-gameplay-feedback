"""Vercel Python serverless function: POST /api/analyze.

Receives a small JSON payload of browser-extracted JPEG frames (base64) plus the
target player's jersey number/color, calls Claude vision, and returns a
structured feedback report. No OpenCV, no file writes, no large uploads — the
whole design fits Vercel's serverless limits.

Exposes an ASGI ``app`` (FastAPI), which Vercel's modern Python runtime detects
automatically as the function entrypoint.
"""
from __future__ import annotations

import json
import os

import anthropic
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

MODEL = os.environ.get("ANTHROPIC_MODEL") or "claude-opus-4-8"
MAX_TOKENS = 4096
# Defensive cap: the browser sends ~10, but never trust the client.
MAX_FRAMES = 20

# JSON schema handed to Claude via output_config (guaranteed-parseable output).
FEEDBACK_JSON_SCHEMA: dict = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "player_identified": {"type": "boolean"},
        "identification_note": {"type": "string"},
        "frame_by_frame": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "frame_number": {"type": "integer"},
                    "timestamp": {"type": "string"},
                    "feedback": {"type": "string"},
                },
                "required": ["frame_number", "timestamp", "feedback"],
            },
        },
        "overall_assessment": {"type": "string"},
        "strengths": {"type": "array", "items": {"type": "string"}},
        "weaknesses": {"type": "array", "items": {"type": "string"}},
        "improvement_suggestions": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "player_identified",
        "identification_note",
        "frame_by_frame",
        "overall_assessment",
        "strengths",
        "weaknesses",
        "improvement_suggestions",
    ],
}


class ApiError(Exception):
    """Carries an HTTP status + client-facing detail message."""

    def __init__(self, status: int, detail: str):
        self.status = status
        self.detail = detail
        super().__init__(detail)


def _system_prompt(jersey_number: str, jersey_color: str) -> str:
    return f"""You are an honest, experienced soccer coach reviewing gameplay \
footage. You are given a sequence of numbered, timestamped frames extracted \
from a single video clip. Each frame may contain multiple players.

Your job is to review ONLY the play of one specific player:
- Jersey number: {jersey_number}
- Jersey color: {jersey_color}

IMPORTANT guidance on identifying the player:
- The jersey number may only be clearly readable in a few frames (motion blur, \
distance, angle) — that is normal and expected.
- Use the JERSEY COLOR as your primary cue to track the player across frames. \
Treat the number as confirmation only where it is legible.
- You do NOT need the number crisply readable in every frame. It is enough to \
confirm the number in at least one or two frames while tracking one consistent \
player in that jersey color across most frames.
- Only set player_identified to false if NO player in that jersey color can be \
found at all, OR if multiple players share that jersey color in a way that makes \
it genuinely ambiguous which one is #{jersey_number}. In that case, explain why \
in identification_note and return an EMPTY frame_by_frame list rather than \
guessing.

When the player IS identified:
- Provide exactly one frame_by_frame entry per frame shown, using the exact \
frame number and timestamp from that frame's text label.
- Each entry should be a short 1-2 sentence note on the player's positioning, \
technique, or decision-making in that frame — or a note that the player is not \
visible in that particular frame.
- Make the overall assessment honest and constructive: call out real weaknesses \
as clearly as strengths. Do not fabricate praise.

Return your report using the required structured JSON format only."""


def _build_content(frames: list[dict]) -> list[dict]:
    content: list[dict] = []
    for i, frame in enumerate(frames, start=1):
        content.append(
            {"type": "text", "text": f"Frame {i} — timestamp {frame['timestamp']}"}
        )
        content.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/jpeg",
                    "data": frame["data"],
                },
            }
        )
    content.append(
        {
            "type": "text",
            "text": (
                "Review the player above across these frames and return the "
                "structured feedback report."
            ),
        }
    )
    return content


def _validate(payload: dict) -> tuple[str, str, list[dict]]:
    if not isinstance(payload, dict):
        raise ApiError(400, "Request body must be a JSON object.")

    jersey_number = str(payload.get("jersey_number", "")).strip()
    jersey_color = str(payload.get("jersey_color", "")).strip()
    frames = payload.get("frames")

    if not jersey_number:
        raise ApiError(400, "jersey_number is required.")
    if not jersey_color:
        raise ApiError(400, "jersey_color is required.")
    if not isinstance(frames, list) or not frames:
        raise ApiError(
            400,
            "No frames were received. The video may not be readable in your "
            "browser — try an MP4 (H.264) file.",
        )
    if len(frames) > MAX_FRAMES:
        frames = frames[:MAX_FRAMES]

    clean: list[dict] = []
    for frame in frames:
        if not isinstance(frame, dict):
            raise ApiError(400, "Each frame must be an object.")
        data = frame.get("data")
        timestamp = frame.get("timestamp")
        if not isinstance(data, str) or not data:
            raise ApiError(400, "A frame is missing its image data.")
        clean.append({"timestamp": str(timestamp or ""), "data": data})

    return jersey_number, jersey_color, clean


def run_analysis(payload: dict) -> dict:
    """Core logic shared by the Vercel app and the local dev server."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ApiError(
            502,
            "ANTHROPIC_API_KEY is not set on the server. The API cannot contact "
            "the AI model.",
        )

    jersey_number, jersey_color, frames = _validate(payload)

    client = anthropic.Anthropic(api_key=api_key)
    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=_system_prompt(jersey_number, jersey_color),
            messages=[{"role": "user", "content": _build_content(frames)}],
            output_config={
                "format": {"type": "json_schema", "schema": FEEDBACK_JSON_SCHEMA}
            },
        )
    except anthropic.APIError as exc:
        raise ApiError(502, f"The AI request failed: {exc}") from exc

    if response.stop_reason == "refusal":
        raise ApiError(502, "The AI model declined to analyze this content.")

    text_block = next(
        (block.text for block in response.content if block.type == "text"), None
    )
    if not text_block:
        raise ApiError(502, "The AI model returned no text content to parse.")

    try:
        return json.loads(text_block)
    except json.JSONDecodeError as exc:
        raise ApiError(502, f"The AI model returned invalid JSON: {exc}") from exc


app = FastAPI()


# Match POST regardless of how Vercel presents the path (with or without the
# /api/analyze prefix), so routing is never the point of failure.
@app.post("/{full_path:path}")
async def analyze(request: Request, full_path: str = "") -> JSONResponse:
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse(
            status_code=400, content={"detail": "Request body is not valid JSON."}
        )
    try:
        report = run_analysis(payload)
        return JSONResponse(status_code=200, content=report)
    except ApiError as exc:
        return JSONResponse(status_code=exc.status, content={"detail": exc.detail})
    except Exception as exc:  # noqa: BLE001 — last-resort guard
        return JSONResponse(
            status_code=500, content={"detail": f"Unexpected server error: {exc}"}
        )
