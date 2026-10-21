"""Bedrock Converse vision judge.

The model only reports observations: is a parcel visible, where, how
confident, and the watermark timestamp printed on the frame. It never
produces a verdict; see ``policy.decide`` for that.

Privacy: the prompt forbids describing people or vehicles, and the output
schema has no field that could carry such a description.
"""
from __future__ import annotations

import hashlib
import os
import time
from dataclasses import replace
from datetime import datetime, timezone, tzinfo
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from countersign import trace
from countersign.policy import Observation, Source

DEFAULT_MODEL_ID_ENV = "BEDROCK_MODEL_ID"
LEGACY_MODEL_ID_ENV = "COUNTERSIGN_BEDROCK_MODEL_ID"
DEVICE_TZ_ENV = "COUNTERSIGN_DEVICE_TZ"
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
    device_tz: tzinfo | None = None,
    source: Source = "live",
) -> Observation:
    """Send one frame to Bedrock Converse and return a validated Observation.

    Ring watermarks are usually local time with no zone. ``device_tz`` (or the
    ``COUNTERSIGN_DEVICE_TZ`` env var) says how to read them. With neither, a
    zone-less watermark stays naive and the policy ignores that frame rather
    than guessing a zone.
    """
    model = (
        model_id
        or os.environ.get(DEFAULT_MODEL_ID_ENV)
        or os.environ.get(LEGACY_MODEL_ID_ENV)
    )
    if not model:
        raise VisionJudgeError(
            f"set {DEFAULT_MODEL_ID_ENV} (or {LEGACY_MODEL_ID_ENV}) or pass model_id"
        )

    frame_id = hashlib.sha256(image_bytes).hexdigest()[:16]
    started = time.perf_counter()
    try:
        response = _converse(client, model, image_bytes, image_format)
    except Exception as exc:
        trace.emit(
            "bedrock_call", "error", model_id=model, frame_id=frame_id,
            latency_ms=round((time.perf_counter() - started) * 1000),
            error=f"{type(exc).__name__}: {exc}",
        )
        raise
    meta = response.get("ResponseMetadata") or {}
    usage = response.get("usage") or {}
    trace.emit(
        "bedrock_call", "ok", model_id=model, frame_id=frame_id,
        latency_ms=round((time.perf_counter() - started) * 1000),
        request_id=meta.get("RequestId"),
        input_tokens=usage.get("inputTokens"), output_tokens=usage.get("outputTokens"),
    )
    obs = parse_response(response, device_tz=device_tz or device_tz_from_env())
    return replace(obs, source=source, frame_id=frame_id)


def _converse(client: Any, model: str, image_bytes: bytes, image_format: str) -> dict[str, Any]:
    response: dict[str, Any] = client.converse(
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
    return response


def device_tz_from_env() -> tzinfo | None:
    name = os.environ.get(DEVICE_TZ_ENV)
    if not name:
        return None
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError as exc:
        raise VisionJudgeError(f"unknown {DEVICE_TZ_ENV}: {name}") from exc


def parse_response(
    response: dict[str, Any], device_tz: tzinfo | None = None
) -> Observation:
    """Extract and validate the tool call. Malformed output raises, never guesses."""
    try:
        blocks = response["output"]["message"]["content"]
    except (KeyError, TypeError) as exc:
        raise VisionJudgeError("response has no message content") from exc

    for block in blocks:
        tool_use = block.get("toolUse") if isinstance(block, dict) else None
        if tool_use and tool_use.get("name") == TOOL_NAME:
            return _to_observation(tool_use.get("input") or {}, device_tz)
    raise VisionJudgeError("model did not call the report tool")


def _to_observation(data: dict[str, Any], device_tz: tzinfo | None) -> Observation:
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
        watermark_ts=_parse_ts(data.get("watermark_timestamp"), device_tz),
    )


def _parse_ts(value: object, device_tz: tzinfo | None = None) -> datetime | None:
    """Parse a watermark. Zone-less values use ``device_tz``, else stay naive."""
    if not isinstance(value, str) or not value.strip():
        return None
    cleaned = value.strip()
    explicit_utc = False
    for suffix in (" UTC", "Z"):
        if cleaned.endswith(suffix) and not cleaned.endswith("ZZ"):
            cleaned = cleaned[: -len(suffix)].strip()
            explicit_utc = True
            break

    dt = _parse_naive_or_aware(cleaned)
    if dt is None:
        return None
    if dt.tzinfo is None:
        if explicit_utc:
            return dt.replace(tzinfo=timezone.utc)
        if device_tz is not None:
            return dt.replace(tzinfo=device_tz)
    return dt


_COMMON_FORMATS = [
    "%Y-%m-%d %H:%M:%S",
    "%m/%d/%Y %I:%M:%S %p",
    "%m/%d/%Y %H:%M:%S",
    "%Y/%m/%d %H:%M:%S",
    "%m/%d/%y %I:%M:%S %p",
]


def _parse_naive_or_aware(text: str) -> datetime | None:
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        pass
    for fmt in _COMMON_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None
