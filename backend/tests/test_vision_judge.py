from datetime import datetime, timezone

import pytest

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


def test_requires_model_id(monkeypatch):
    monkeypatch.delenv("COUNTERSIGN_BEDROCK_MODEL_ID", raising=False)
    with pytest.raises(VisionJudgeError):
        judge_frame(StubClient({}), b"img")
