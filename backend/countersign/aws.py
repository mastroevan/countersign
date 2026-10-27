"""boto3 client construction with a region fallback.

``boto3.client`` raises NoRegionError when neither env vars nor the AWS
profile name a region. Honor whatever boto3 resolves, else use us-east-1.
"""
from __future__ import annotations

from typing import Any

import boto3

DEFAULT_REGION = "us-east-1"


def make_client(service: str) -> Any:
    region = boto3.session.Session().region_name or DEFAULT_REGION
    return boto3.client(service, region_name=region)  # type: ignore[call-overload]


class PixelBedrock:
    """Stands in for Bedrock: says 'parcel' if the synthetic parcel's pixels are present."""

    def converse(self, **kw: Any) -> dict[str, Any]:
        import io
        from datetime import datetime, timedelta, timezone
        from PIL import Image

        img = kw["messages"][0]["content"][0]["image"]["source"]["bytes"]
        pixel = Image.open(io.BytesIO(img)).convert("RGB").getpixel((320, 310))
        assert isinstance(pixel, tuple)
        r, g, b = pixel[:3]
        visible = r > 160 and b < 130  # parcel box is (185, 142, 95); porch floor is grey
        inp = {
            "parcel_visible": visible,
            "confidence": 0.95,
            "location": "porch" if visible else "none",
            "watermark_timestamp": (datetime.now(timezone.utc) + timedelta(seconds=1)).isoformat(),
        }
        return {
            "output": {"message": {"content": [{"toolUse": {"name": "report_observation", "input": inp}}]}},
            "ResponseMetadata": {"RequestId": "stub-bedrock-req"},
        }

