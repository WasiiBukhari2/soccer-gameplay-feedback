"""Build the Claude prompt, call the API, and parse the structured response."""
from __future__ import annotations

import base64
import json

import anthropic

from app import config
from app.models.schemas import FEEDBACK_JSON_SCHEMA, FeedbackReport
from app.services.video_frames import FrameSample


class AnalysisError(Exception):
    """Raised for any failure producing a feedback report from Claude."""


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


def _build_content(frames: list[FrameSample]) -> list[dict]:
    """Alternating text-label + image blocks, one pair per frame."""
    content: list[dict] = []
    for i, frame in enumerate(frames, start=1):
        content.append(
            {
                "type": "text",
                "text": f"Frame {i} — timestamp {frame.timestamp_label}",
            }
        )
        image_bytes = frame.path.read_bytes()
        b64 = base64.standard_b64encode(image_bytes).decode("ascii")
        content.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/jpeg",
                    "data": b64,
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


def analyze_frames(
    frames: list[FrameSample],
    jersey_number: str,
    jersey_color: str,
) -> FeedbackReport:
    if not config.ANTHROPIC_API_KEY:
        raise AnalysisError(
            "ANTHROPIC_API_KEY is not set. The server cannot contact the AI "
            "model. Set it in your environment / .env file."
        )

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    try:
        response = client.messages.create(
            model=config.ANTHROPIC_MODEL,
            max_tokens=4096,
            system=_system_prompt(jersey_number, jersey_color),
            messages=[{"role": "user", "content": _build_content(frames)}],
            output_config={
                "format": {
                    "type": "json_schema",
                    "schema": FEEDBACK_JSON_SCHEMA,
                }
            },
        )
    except anthropic.APIError as exc:
        raise AnalysisError(f"The AI request failed: {exc}") from exc

    if response.stop_reason == "refusal":
        raise AnalysisError(
            "The AI model declined to analyze this content."
        )

    text_block = next(
        (block.text for block in response.content if block.type == "text"),
        None,
    )
    if not text_block:
        raise AnalysisError("The AI model returned no text content to parse.")

    try:
        data = json.loads(text_block)
    except json.JSONDecodeError as exc:
        raise AnalysisError(
            f"The AI model returned invalid JSON: {exc}"
        ) from exc

    try:
        return FeedbackReport(**data)
    except Exception as exc:  # pydantic ValidationError, etc.
        raise AnalysisError(
            f"The AI response did not match the expected format: {exc}"
        ) from exc
