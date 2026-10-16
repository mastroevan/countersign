"""Bedrock Converse vision judge.

The model only reports observations: is a parcel visible, where, how
confident, and the watermark timestamp printed on the frame. It never
produces a verdict; see ``policy.decide`` for that.

Privacy: the prompt forbids describing people or vehicles, and the output
schema has no field that could carry such a description.
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import Any

from countersign.policy import Observation

DEFAULT_MODEL_ID_ENV = "COUNTERSIGN_BEDROCK_MODEL_ID"
TOOL_NAME = "report_observation"

SYSTEM_PROMPT = (
    "You inspect a single doorbell-camera frame of a porch or step. "
    "Report only whether a parcel (box, package or padded mailer) is visible, "
    "where it is, and your confidence. Read the timestamp watermark burned "
    "into the frame, if any, but never treat the watermark as evidence of a "
    "parcel. Do not identify or describe people, faces or vehicles. "
    "Do not decide whether a delivery happened. Always answer by calling "
    f"the {TOOL_NAME} tool."
)

TOOL_CONFIG: dict[str, Any] = {
    "tools": [
        {
            "toolSpec": {
                "name": TOOL_NAME,
                "description": "Report parcel visibility for this frame.",
                "inputSchema": {
                    "json": {
                        "type": "object",
                        "properties": {
                            "parcel_visible": {"type": "boolean"},
                            "location": {
                                "type": "string",
                                "enum": ["step", "porch", "other", "none"],
                            },
                            "confidence": {
                                "type": "number",
                                "minimum": 0,
                                "maximum": 1,
                            },
                            "watermark_timestamp": {
                                "type": "string",
                                "description": "ISO 8601 timestamp read from "
                                "the frame watermark, or empty if unreadable.",
                            },
                        },
                        "required": ["parcel_visible", "location", "confidence"],
                    }
                },
            }
        }
    ],
    "toolChoice": {"tool": {"name": TOOL_NAME}},
}


class VisionJudgeError(RuntimeError):
    """The model response could not be turned into an Observation."""


def judge_frame(
    client: Any,
    image_bytes: bytes,
    image_format: str = "jpeg",
    model_id: str | None = None,
) -> Observation:
    """Send one frame to Bedrock Converse and return a validated Observation."""
    model = model_id or os.environ.get(DEFAULT_MODEL_ID_ENV)
    if not model:
        raise VisionJudgeError(f"set {DEFAULT_MODEL_ID_ENV} or pass model_id")

    response = client.converse(
        modelId=model,
        system=[{"text": SYSTEM_PROMPT}],
        messages=[
            {
                "role": "user",
                "content": [
                    {"image": {"format": image_format, "source": {"bytes": image_bytes}}},
                    {"text": "Report your observation for this frame."},
                ],
            }
        ],
        toolConfig=TOOL_CONFIG,
        inferenceConfig={"temperature": 0, "maxTokens": 300},
    )
    return parse_response(response)


def parse_response(response: dict[str, Any]) -> Observation:
    """Extract and validate the tool call. Malformed output raises, never guesses."""
    try:
        blocks = response["output"]["message"]["content"]
    except (KeyError, TypeError) as exc:
        raise VisionJudgeError("response has no message content") from exc

    for block in blocks:
        tool_use = block.get("toolUse") if isinstance(block, dict) else None
        if tool_use and tool_use.get("name") == TOOL_NAME:
            return _to_observation(tool_use.get("input") or {})
    raise VisionJudgeError("model did not call the report tool")


def _to_observation(data: dict[str, Any]) -> Observation:
    visible = data.get("parcel_visible")
    if not isinstance(visible, bool):
        raise VisionJudgeError("parcel_visible must be a boolean")

    conf = data.get("confidence")
    if isinstance(conf, bool) or not isinstance(conf, (int, float)):
        raise VisionJudgeError("confidence must be a number")
    if not 0.0 <= conf <= 1.0:
        raise VisionJudgeError("confidence out of range")

    location = data.get("location")
    if location in (None, "none"):
        location = None
    elif not isinstance(location, str):
        raise VisionJudgeError("location must be a string")

    return Observation(
        parcel_visible=visible,
        confidence=float(conf),
        location=location,
        watermark_ts=_parse_ts(data.get("watermark_timestamp")),
    )


def _parse_ts(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.strip())
    except ValueError:
        return None
