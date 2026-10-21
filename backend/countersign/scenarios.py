"""Demo scenarios: ``python -m countersign.scenarios <name>``.

    delivered_seen       carrier says delivered, the Package stream shows a parcel  -> VERIFIED
    delivered_not_seen   carrier says delivered, the Motion stream shows no parcel  -> DISPUTED
    unreadable           carrier says delivered, the stream yields no frames        -> INCONCLUSIVE

Each scenario creates a test-mode EasyPost tracker, binds it to one stream on
the running backend, posts the resulting ``tracker.updated`` webhook, and
prints the pipeline trace until a verdict. What is staged, and said so on
screen: the tracker-to-stream wiring, the scan time (set to now so it lines up
with a live view), and, with --offline, the frames (synthetic, never claimable).
The EasyPost call, the Ring calls, the Bedrock judgment and the policy are real.

The backend must run with COUNTERSIGN_SCENARIOS=true. Live mode needs
EASYPOST_API_KEY (a test key, EZTK...), RING_DEVICE_PACKAGE / RING_DEVICE_MOTION
(the Playground device ids for those streams), and a Ring token on the backend.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import hmac
import json
import os
import sys
import unicodedata
import uuid
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx

from countersign.bindings import Stream
from countersign.trackers import EASYPOST_KEY_ENV, EASYPOST_URL

TEST_TRACKING_CODE = "EZ4000000004"  # EasyPost test code: status delivered
TERMINAL = {"verification_complete", "verification_failed"}
DEVICE_ENV = {"package": "RING_DEVICE_PACKAGE", "motion": "RING_DEVICE_MOTION"}


@dataclass(frozen=True)
class Scenario:
    name: str
    stream: Stream
    expected: str  # verdict
    blurb: str


SCENARIOS = {
    s.name: s
    for s in [
        Scenario("delivered_seen", "package", "VERIFIED", "carrier delivered; parcel visible on the step"),
        Scenario("delivered_not_seen", "motion", "DISPUTED", "carrier delivered; no parcel after the scan"),
        Scenario("unreadable", "timeout", "INCONCLUSIVE", "carrier delivered; camera stream times out"),
    ]
}


class ScenarioError(RuntimeError):
    """Setup problem (exit 2), as opposed to an unexpected verdict (exit 1)."""


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def local_tracker(scan_at: datetime) -> dict[str, Any]:
    """Offline stand-in for an EasyPost test tracker. Labeled local-only."""
    return {
        "id": f"trk_local_{uuid.uuid4().hex[:12]}",
        "object": "Tracker",
        "mode": "test",
        "tracking_code": TEST_TRACKING_CODE,
        "status": "delivered",
        "tracking_details": [{"status": "delivered", "datetime": _z(scan_at)}],
    }


async def create_easypost_tracker(http: httpx.AsyncClient, api_key: str) -> dict[str, Any]:
    if not api_key.startswith("EZTK"):
        raise ScenarioError(f"{EASYPOST_KEY_ENV} must be an EasyPost TEST key (EZTK...); refusing to use it")
    r = await http.post(
        EASYPOST_URL, json={"tracker": {"tracking_code": TEST_TRACKING_CODE}}, auth=(api_key, "")
    )
    if r.status_code >= 400:
        raise ScenarioError(f"EasyPost tracker creation failed (HTTP {r.status_code}): {r.text[:200]}")
    tracker: dict[str, Any] = r.json()
    if tracker.get("status") != "delivered":
        raise ScenarioError(f"test tracker is {tracker.get('status')!r}, expected delivered")
    return tracker


def build_event(tracker: dict[str, Any], scan_at: datetime | None) -> dict[str, Any]:
    """A tracker.updated event. ``scan_at`` overrides the delivered timestamp (staged)."""
    result = json.loads(json.dumps(tracker))
    result["mode"] = "test"
    if scan_at is not None:
        details = [d for d in result.get("tracking_details", []) if d.get("status") == "delivered"]
        if details:
            details[-1]["datetime"] = _z(scan_at)
        else:
            result.setdefault("tracking_details", []).append({"status": "delivered", "datetime": _z(scan_at)})
    return {
        "id": f"evt_scn_{uuid.uuid4().hex[:12]}",
        "object": "Event",
        "mode": "test",
        "description": "tracker.updated",
        "result": result,
    }


def sign(secret: str, body: bytes) -> str:
    key = unicodedata.normalize("NFKD", secret).encode()
    return "hmac-sha256-hex=" + hmac.new(key, body, hashlib.sha256).hexdigest()


def format_event(ev: dict[str, Any]) -> str:
    mark = {"ok": "+", "error": "!", "started": ">", "info": "."}.get(ev["status"], "?")
    ts = ev["ts"][11:19]
    data = {k: v for k, v in ev["data"].items() if k != "payload" and v is not None}
    detail = " ".join(f"{k}={_short(v)}" for k, v in data.items())
    return f"{ts} {mark} {ev['stage']:<22} {detail}".rstrip()


async def stream_trace(
    http: httpx.AsyncClient, backend: str, vid: str, timeout_s: float
) -> AsyncIterator[dict[str, Any]]:
    """Yield trace events until a terminal one (or the timeout)."""
    deadline = asyncio.get_running_loop().time() + timeout_s

    async def events() -> AsyncIterator[dict[str, Any]]:
        async with http.stream(
            "GET", f"{backend}/api/trace", params={"verification_id": vid}, timeout=None
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if line.startswith("data: ") and line != "data: {}":
                    yield json.loads(line[6:])

    gen = events()
    try:
        while True:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise ScenarioError(f"no verdict within {timeout_s:.0f}s (is the backend running?)")
            try:
                ev = await asyncio.wait_for(gen.__anext__(), remaining)
            except StopAsyncIteration:
                return
            except asyncio.TimeoutError:
                raise ScenarioError(f"no verdict within {timeout_s:.0f}s")
            yield ev
            if ev["stage"] in TERMINAL:
                return
    finally:
        await gen.aclose()  # type: ignore[attr-defined]


async def run_scenario(
    name: str,
    backend: str,
    http: httpx.AsyncClient,
    *,
    offline: bool = False,
    scan_now: bool = True,
    recheck_now: bool = False,
    timeout_s: float = 90.0,
    out: Any = sys.stdout,
    env: Mapping[str, str] | None = None,
) -> int:
    env = os.environ if env is None else env
    sc = SCENARIOS[name]

    def say(msg: str) -> None:
        print(msg, file=out, flush=True)

    backend = backend.rstrip("/")

    say(f"== {name}: {sc.blurb} (expect {sc.expected})")
    say(f"   STAGED: tracker bound to the {sc.stream!r} stream"
        + ("; scan time set to now" if scan_now else "")
        + ("; OFFLINE synthetic frames, not claimable, no EasyPost/Ring calls" if offline else ""))

    # 1. tracker
    scan_at = now_utc()
    if offline:
        tracker = local_tracker(scan_at)
        say(f"   tracker {tracker['id']} (local stand-in)")
    else:
        key = env.get(EASYPOST_KEY_ENV, "")
        if not key:
            raise ScenarioError(f"set {EASYPOST_KEY_ENV} (EasyPost test key) or use --offline")
        tracker = await create_easypost_tracker(http, key)
        say(f"   tracker {tracker['id']} (EasyPost test mode)")

    # 2. stream binding on the backend
    device_id = None
    if not offline and sc.stream in DEVICE_ENV:
        device_id = env.get(DEVICE_ENV[sc.stream])
        if not device_id:
            raise ScenarioError(f"set {DEVICE_ENV[sc.stream]} to the Playground device id of the {sc.stream} stream")
    r = await http.post(
        f"{backend}/api/bindings",
        json={"key": tracker["id"], "stream": sc.stream, "device_id": device_id, "offline": offline},
    )
    if r.status_code == 404:
        raise ScenarioError("backend refused the binding: start it with COUNTERSIGN_SCENARIOS=true")
    r.raise_for_status()

    # 3. webhook
    event = build_event(tracker, scan_at if scan_now else None)
    body = json.dumps(event).encode()
    headers = {"content-type": "application/json"}
    if env.get("EASYPOST_WEBHOOK_SECRET"):
        headers["x-hmac-signature"] = sign(env["EASYPOST_WEBHOOK_SECRET"], body)
    r = await http.post(f"{backend}/webhooks/easypost", content=body, headers=headers)
    if r.status_code >= 400:
        raise ScenarioError(f"webhook rejected (HTTP {r.status_code}): {r.text[:200]}")
    vid = r.json()["id"]
    say(f"   webhook accepted -> verification {vid}\n")

    # 4. trace
    failed = False
    async for ev in stream_trace(http, backend, vid, timeout_s):
        say("   " + format_event(ev))
        failed = failed or ev["stage"] == "verification_failed"
    if failed:
        say("\nRESULT: the check failed without a verdict (see the error above)")
        return 1

    if recheck_now:
        say("\n   re-checking now ...")
        (await http.post(f"{backend}/verifications/{vid}/recheck", timeout=timeout_s)).raise_for_status()

    v = (await http.get(f"{backend}/verifications/{vid}")).json()
    verdict = v["result"]["verdict"]
    say(f"\nRESULT: {verdict} - {v['result']['reason']}")
    if v.get("recheck_state") == "scheduled":
        say(f"        provisional; re-check due {v['recheck_due_at']}")
    if verdict == sc.expected:
        say(f"        matches expected {sc.expected}")
        return 0
    say(f"        UNEXPECTED: wanted {sc.expected}")
    return 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m countersign.scenarios", description=__doc__.split("\n")[0])
    ap.add_argument("scenario", choices=sorted(SCENARIOS))
    ap.add_argument("--backend", default=os.environ.get("COUNTERSIGN_URL", "http://localhost:8000"))
    ap.add_argument("--offline", action="store_true", help="local tracker + synthetic frames; no EasyPost or Ring")
    ap.add_argument("--use-tracker-time", action="store_true", help="keep the tracker's own delivered time")
    ap.add_argument("--recheck-now", action="store_true", help="run the re-check immediately afterwards")
    ap.add_argument("--timeout", type=float, default=90.0)
    ap.add_argument("--dry-run", action="store_true", help="print the plan only")
    args = ap.parse_args(argv)

    sc = SCENARIOS[args.scenario]
    if args.dry_run:
        print(f"{sc.name}: stream={sc.stream} expected={sc.expected} offline={args.offline} backend={args.backend}")
        return 0

    async def go() -> int:
        async with httpx.AsyncClient(timeout=30) as http:
            return await run_scenario(
                args.scenario, args.backend, http, offline=args.offline,
                scan_now=not args.use_tracker_time, recheck_now=args.recheck_now, timeout_s=args.timeout,
            )

    try:
        return asyncio.run(go())
    except ScenarioError as exc:
        print(f"setup problem: {exc}", file=sys.stderr)
        return 2
    except httpx.ConnectError:
        print(f"cannot reach the backend at {args.backend}", file=sys.stderr)
        return 2


def _z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _short(v: Any) -> str:
    s = json.dumps(v) if not isinstance(v, str) else v
    return s if len(s) <= 60 else s[:57] + "..."


if __name__ == "__main__":
    raise SystemExit(main())
