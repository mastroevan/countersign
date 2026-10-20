from datetime import datetime, timezone

import pytest
from zoneinfo import ZoneInfo

from countersign.vision_judge import (
    TOOL_NAME,
    VisionJudgeError,
    judge_frame,
    parse_response,
)


def resp(**inp):
    return {
        "output": {
            "message": {"content": [{"toolUse": {"name": TOOL_NAME, "input": inp}}]}
        }
    }


class StubClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def converse(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


def test_parses_valid_observation():
    o = parse_response(
        resp(
            parcel_visible=True,
            location="porch",
            confidence=0.9,
            watermark_timestamp="2026-10-15T12:01:00+00:00",
        )
    )
    assert o.parcel_visible and o.location == "porch" and o.confidence == 0.9
    assert o.watermark_ts == datetime(2026, 10, 15, 12, 1, tzinfo=timezone.utc)


def test_location_none_and_bad_timestamp():
    o = parse_response(
        resp(parcel_visible=False, location="none", confidence=1, watermark_timestamp="garbage")
    )
    assert o.location is None and o.watermark_ts is None


@pytest.mark.parametrize(
    "bad",
    [
        dict(parcel_visible="yes", location="porch", confidence=0.9),
        dict(parcel_visible=True, location="porch", confidence=1.5),
        dict(parcel_visible=True, location="porch", confidence="high"),
        dict(parcel_visible=True, location="porch", confidence=True),
        dict(parcel_visible=True, location="porch"),
    ],
)
def test_rejects_malformed_input(bad):
    with pytest.raises(VisionJudgeError):
        parse_response(resp(**bad))


def test_rejects_missing_tool_call():
    r = {"output": {"message": {"content": [{"text": "A parcel is there."}]}}}
    with pytest.raises(VisionJudgeError):
        parse_response(r)


def test_judge_frame_request_shape():
    client = StubClient(resp(parcel_visible=True, location="step", confidence=0.8))
    o = judge_frame(client, b"img", model_id="test-model")
    assert o.parcel_visible
    call = client.calls[0]
    assert call["modelId"] == "test-model"
    assert call["toolConfig"]["toolChoice"] == {"tool": {"name": TOOL_NAME}}
    assert call["messages"][0]["content"][0]["image"]["source"]["bytes"] == b"img"


def _human(ts):
    return resp(parcel_visible=True, location="porch", confidence=0.9, watermark_timestamp=ts)


def test_zoneless_watermark_stays_naive_without_device_tz():
    # Guessing UTC would shift frames by hours; the policy ignores naive times.
    o = parse_response(_human("10/15/2026 12:01:00 PM"))
    assert o.watermark_ts == datetime(2026, 10, 15, 12, 1)
    assert o.watermark_ts.tzinfo is None


def test_zoneless_watermark_uses_device_tz():
    tz = ZoneInfo("America/New_York")
    o = parse_response(_human("10/15/2026 12:01:00 PM"), device_tz=tz)
    assert o.watermark_ts == datetime(2026, 10, 15, 16, 1, tzinfo=timezone.utc)


def test_explicit_utc_suffix_wins_over_device_tz():
    tz = ZoneInfo("America/New_York")
    o = parse_response(_human("10/15/2026 12:01:00 PM UTC"), device_tz=tz)
    assert o.watermark_ts == datetime(2026, 10, 15, 12, 1, tzinfo=timezone.utc)


def test_device_tz_from_env(monkeypatch):
    monkeypatch.setenv("BEDROCK_MODEL_ID", "m")
    monkeypatch.setenv("COUNTERSIGN_DEVICE_TZ", "America/Chicago")
    client = StubClient(_human("2026-10-15 12:01:00"))
    o = judge_frame(client, b"img")
    assert o.watermark_ts == datetime(2026, 10, 15, 17, 1, tzinfo=timezone.utc)


def test_judge_tags_source_and_frame_id(monkeypatch):
    monkeypatch.setenv("BEDROCK_MODEL_ID", "m")
    o = judge_frame(StubClient(_human("")), b"img", source="synthetic")
    assert o.source == "synthetic"
    assert o.frame_id and len(o.frame_id) == 16


def test_requires_model_id(monkeypatch):
    monkeypatch.delenv("BEDROCK_MODEL_ID", raising=False)
    monkeypatch.delenv("COUNTERSIGN_BEDROCK_MODEL_ID", raising=False)
    with pytest.raises(VisionJudgeError):
        judge_frame(StubClient({}), b"img")


def test_reads_bedrock_model_id_from_env(monkeypatch):
    monkeypatch.setenv("BEDROCK_MODEL_ID", "model-via-bedrock-env")
    monkeypatch.delenv("COUNTERSIGN_BEDROCK_MODEL_ID", raising=False)
    client = StubClient(resp(parcel_visible=True, location="step", confidence=0.8))
    judge_frame(client, b"img")
    assert client.calls[0]["modelId"] == "model-via-bedrock-env"
