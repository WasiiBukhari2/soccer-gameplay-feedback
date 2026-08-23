"""Vercel Python serverless function: POST /api/analyze.

Receives a small JSON payload of browser-extracted JPEG frames (base64) plus the
target player's jersey number/color, calls Claude vision, and returns a
structured feedback report. No OpenCV, no file writes, no large uploads — the
whole design fits Vercel's serverless limits.

Everything is inlined in this single file on purpose: Vercel bundles each
api/*.py file as its own function, so keeping dependencies to `anthropic` + the
standard library avoids cross-module import surprises at build time.
"""
from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler

import anthropic

MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-opus-4-8")
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
    """Core logic shared by the Vercel handler and the local dev server."""
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


class handler(BaseHTTPRequestHandler):
    """Vercel Python entrypoint."""

    def _send_json(self, status: int, body: dict) -> None:
        payload = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(payload)

    def do_OPTIONS(self) -> None:  # noqa: N802 (name mandated by BaseHTTPRequestHandler)
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_POST(self) -> None:  # noqa: N802
        try:
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b""
            try:
                payload = json.loads(raw or b"{}")
            except json.JSONDecodeError:
                raise ApiError(400, "Request body is not valid JSON.")
            report = run_analysis(payload)
            self._send_json(200, report)
        except ApiError as exc:
            self._send_json(exc.status, {"detail": exc.detail})
        except Exception as exc:  # noqa: BLE001 — last-resort guard
            self._send_json(500, {"detail": f"Unexpected server error: {exc}"})
