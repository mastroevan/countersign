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
