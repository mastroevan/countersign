"""Claim drafting and evidence packets.

Both are deterministic (no LLM) and gated behind human approval by the API
layer. Frames are stored byte-for-byte, so the Ring watermark stays intact for
audit. Nothing here describes people or vehicles.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
from dataclasses import dataclass
from typing import Any, Protocol

from countersign.aws import make_client
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
        "draft_text": draft_text(v),
        "evidence_frame_ids": [e.frame_id for e in r.evidence],
        "requires_approval": True,
    }


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def draft_text(v: Verification) -> str:
    """Plain-text claim body for a human to review and send."""
    assert v.result is not None
    r, d = v.result, v.result.decision
    return (
        f"Tracking number: {v.tracking_code or 'unknown'}\n"
        f"The carrier recorded this parcel as delivered at {r.delivered_at.isoformat()}.\n"
        f"My doorbell camera captured {d.negative_frames} confident frame(s) at or after "
        "that time showing no parcel on the step or porch, and none showing one.\n"
        "Frames and an integrity hash are attached in the evidence packet. "
        "I am requesting investigation of this delivery."
    )


def build_packet(v: Verification) -> tuple[bytes, dict[str, bytes], str]:
    """Return (manifest_bytes, {frame_path: jpeg}, sha256_of_manifest).

    The manifest lists every frame with its own SHA-256, so the one manifest
    hash commits to the whole packet. Serialization is canonical (sorted keys,
    fixed separators) so the hash is reproducible from the same inputs.
    """
    assert v.result is not None
    frames: dict[str, bytes] = {}
    entries = []
    for e, f in zip(v.result.evidence, v.result.frames):
        path = f"frames/{f.frame_id}.jpg"
        frames[path] = f.jpeg
        o = e.observation
        entries.append(
            {
                "file": path,
                "sha256": _sha256(f.jpeg),
                "bytes": len(f.jpeg),
                "source": f.source,
                "captured_at": f.captured_at.isoformat(),
                "watermark_ts": o.watermark_ts.isoformat() if o and o.watermark_ts else None,
                "parcel_visible": o.parcel_visible if o else None,
                "confidence": o.confidence if o else None,
                "location": o.location if o else None,
            }
        )
    manifest = {
        "verification_id": v.id,
        "tracking_code": v.tracking_code,
        "carrier_delivered_at": v.result.delivered_at.isoformat(),
        "verdict": v.result.decision.verdict.value,
        "reason": v.result.decision.reason,
        "frames": entries,
        "note": "Frames are unmodified; the Ring watermark is preserved. "
        "The watermark is not evidence of a parcel.",
    }
    manifest_bytes = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    return manifest_bytes, frames, _sha256(manifest_bytes)


@dataclass(frozen=True)
class PacketRef:
    location: str
    sha256: str  # SHA-256 of manifest.json, which lists each frame's SHA-256


class EvidenceSink(Protocol):
    async def put_packet(self, v: Verification) -> PacketRef:
        """Store manifest + frames, return where and the manifest SHA-256."""


class MemorySink:
    """Test/dev sink that keeps packets in memory."""

    def __init__(self) -> None:
        self.packets: dict[str, dict[str, bytes]] = {}

    async def put_packet(self, v: Verification) -> PacketRef:
        manifest, frames, digest = build_packet(v)
        self.packets[v.id] = {"manifest.json": manifest, **frames}
        return PacketRef(f"memory://evidence/{v.id}", digest)


class S3Sink:
    def __init__(self, bucket: str | None = None, client: Any = None) -> None:
        self.bucket = bucket or os.environ.get(S3_BUCKET_ENV, "")
        if not self.bucket:
            raise RuntimeError(f"set {S3_BUCKET_ENV} to store evidence packets in S3")
        if client is None:
            client = make_client("s3")
        self.client = client

    async def put_packet(self, v: Verification) -> PacketRef:
        manifest, frames, digest = build_packet(v)
        prefix = f"evidence/{v.id}"
        objects = {f"{prefix}/manifest.json": (manifest, "application/json")}
        for path, jpeg in frames.items():
            objects[f"{prefix}/{path}"] = (jpeg, "image/jpeg")
        for key, (body, ctype) in objects.items():
            await asyncio.to_thread(
                self.client.put_object,
                Bucket=self.bucket,
                Key=key,
                Body=body,
                ContentType=ctype,
                ServerSideEncryption="AES256",
                ChecksumAlgorithm="SHA256",
                Metadata={"sha256": hashlib.sha256(body).hexdigest()},
            )
        return PacketRef(f"s3://{self.bucket}/{prefix}/", digest)
