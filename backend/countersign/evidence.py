"""Claim drafting and evidence packets.

Both are deterministic (no LLM) and gated behind human approval by the API
layer. Frames are stored byte-for-byte, so the Ring watermark stays intact for
audit. Nothing here describes people or vehicles.
"""
from __future__ import annotations

import asyncio
import json
import os
from typing import Any, Protocol

from countersign.ledger import Verification

S3_BUCKET_ENV = "COUNTERSIGN_EVIDENCE_BUCKET"


def draft_claim(v: Verification) -> dict[str, Any]:
    """Template a not-delivered claim from a DISPUTED verification."""
    assert v.result is not None
    r = v.result
    d = r.decision
    return {
        "tracking_code": v.tracking_code,
        "claim_type": "carrier_scanned_delivered_parcel_not_observed",
        "carrier_delivered_at": r.delivered_at.isoformat(),
        "summary": (
            f"Carrier reported delivery at {r.delivered_at.isoformat()}. "
            f"{d.negative_frames} confident camera frame(s) after that time show "
            "no parcel on the step or porch."
        ),
        "decision_reason": d.reason,
        "evidence_frame_ids": [e.frame_id for e in r.evidence],
        "requires_approval": True,
    }


def build_manifest(v: Verification) -> dict[str, Any]:
    assert v.result is not None
    return {
        "verification_id": v.id,
        "tracking_code": v.tracking_code,
        "summary": v.result.to_dict(),
        "note": "Frames are unmodified; the Ring watermark is preserved.",
    }


class EvidenceSink(Protocol):
    async def put_packet(self, v: Verification) -> str:
        """Store manifest + frames, return a location string."""


class MemorySink:
    """Test/dev sink that keeps packets in memory."""

    def __init__(self) -> None:
        self.packets: dict[str, dict[str, bytes]] = {}

    async def put_packet(self, v: Verification) -> str:
        assert v.result is not None
        files = {"manifest.json": json.dumps(build_manifest(v), indent=2).encode()}
        for e, f in zip(v.result.evidence, v.result.frames):
            files[f"frames/{e.frame_id}.jpg"] = f.jpeg
        self.packets[v.id] = files
        return f"memory://evidence/{v.id}"


class S3Sink:
    def __init__(self, bucket: str | None = None, client: Any = None) -> None:
        self.bucket = bucket or os.environ.get(S3_BUCKET_ENV, "")
        if not self.bucket:
            raise RuntimeError(f"set {S3_BUCKET_ENV} to store evidence packets in S3")
        if client is None:
            import boto3

            client = boto3.client("s3")
        self.client = client

    async def put_packet(self, v: Verification) -> str:
        assert v.result is not None
        prefix = f"evidence/{v.id}"
        objects = {f"{prefix}/manifest.json": (json.dumps(build_manifest(v)).encode(), "application/json")}
        for f in v.result.frames:
            objects[f"{prefix}/frames/{f.frame_id}.jpg"] = (f.jpeg, "image/jpeg")
        for key, (body, ctype) in objects.items():
            await asyncio.to_thread(
                self.client.put_object,
                Bucket=self.bucket,
                Key=key,
                Body=body,
                ContentType=ctype,
                ServerSideEncryption="AES256",
            )
        return f"s3://{self.bucket}/{prefix}/"
