"""Pydantic response models and the JSON schema passed to Claude's output_config."""
from __future__ import annotations

from pydantic import BaseModel


class FrameFeedback(BaseModel):
    frame_number: int
    timestamp: str
    feedback: str


class FeedbackReport(BaseModel):
    player_identified: bool
    identification_note: str
    frame_by_frame: list[FrameFeedback]
    overall_assessment: str
    strengths: list[str]
    weaknesses: list[str]
    improvement_suggestions: list[str]


# JSON schema handed to Claude via output_config.format (type: json_schema).
# Mirrors FeedbackReport exactly. additionalProperties:false on the top object
# so the model cannot invent extra keys.
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
