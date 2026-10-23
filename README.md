# Countersign

Verify a carrier's "delivered" scan against doorbell-camera evidence, with a
deterministic policy and a human in the loop. Built for the Amazon Developer
Hackathon (Ring track, with an Alexa+-style MCP server).

![Dashboard](docs/screenshots/dashboard_full.png)

## What it does
1. A carrier "delivered" event arrives (EasyPost webhook, a tracking-code lookup, or an
   MCP tool call).
2. The backend finds the door camera, refuses any device with `e2e_encryption.enabled`
   not explicitly `false`, opens a WHEP live-view session and samples frames.
3. Amazon Bedrock (Converse, forced tool use) reports **only** observations per frame:
   is a parcel visible, where, how confident, and the watermark time. It never decides.
4. `policy.py` turns observations into **VERIFIED / DISPUTED / INCONCLUSIVE** with plain
   Python. A DISPUTED verdict is provisional until a re-check runs.
5. Claim drafts and S3 evidence packets are built only after a named human approves them.

Design rules: the model never produces a verdict; no people, faces or vehicles are
described; the Ring watermark is preserved in evidence but is never evidence of a parcel;
synthetic frames can never back a claim.

## Stack
Python 3.11+, FastAPI, aiortc, boto3 (Bedrock Converse, S3), FastMCP (Streamable HTTP,
protocol 2025-11-25), Next.js 14 + Tailwind, `@modelcontextprotocol/sdk`.

## Status (honest)
- Covered by 150+ automated tests, strict `mypy`, and a frontend typecheck and build.
  Ring, Bedrock, S3 and EasyPost are exercised through mocks and fakes in tests.
- **Not yet run end to end against live Ring, Bedrock, S3 or EasyPost.** The clients are
  written to the documented APIs; treat live behavior as unverified. See
  `docs/DEVLOG.md` and `docs/PRODUCT_FEEDBACK.md`.
- The ledger is in memory (a restart loses data and pending timers). Routes are
  unauthenticated apart from the optional webhook HMAC, so run it locally only.
- Strands Agents and Bedrock AgentCore are not used.
- The vision judge has only been evaluated on synthetic frames.

## Backend setup
```bash
cd backend
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
pytest tests/ && mypy countersign
uvicorn countersign.main:app --reload --port 8000
```

Copy `.env.example` to `backend/.env`. Variables: `RING_ACCESS_TOKEN`, `BEDROCK_MODEL_ID`,
`AWS_REGION`, `COUNTERSIGN_DEVICE_TZ` (IANA zone of the camera's watermark),
`EASYPOST_WEBHOOK_SECRET` (enforces HMAC when set), `COUNTERSIGN_EVIDENCE_BUCKET`,
`EASYPOST_API_KEY`, `RECHECK_DELAY_S` (600 default, 60 for demos), `PUBLIC_BASE_URL`,
`COUNTERSIGN_OFFLINE_SIMULATION=true` (synthetic frames; can never back a claim).

## Frontend
```bash
cd web && npm install && npm run dev      # http://localhost:3000
npm run typecheck && npm run build
```
Pages: `/` ledger, split-screen audit view, live trace panel, approval controls;
`/alexa` an MCP client (voice in and out) that talks to the server below.

## MCP server
Tools at `/mcp/` (Streamable HTTP): `verify_delivery`, `recheck_door`,
`get_delivery_ledger`, `build_claim_packet`. There is deliberately no approval tool;
claims and packets need a human approval via `POST /verifications/{id}/approvals`.

## Live trace and demo scenarios
`GET /api/trace` is a Server-Sent Events stream of pipeline stages (webhook, device
discovery, encryption check, WHEP session, sampled frames, Bedrock call with model ID /
request ID / latency, judgment, the policy rule that fired, re-check). Filter with
`?verification_id=`, resume with `Last-Event-ID`, or pass `follow=false` to replay history.
Events carry metadata only, never image bytes.

```bash
# backend started with COUNTERSIGN_SCENARIOS=true
python -m countersign.scenarios delivered_seen --offline      # -> VERIFIED
python -m countersign.scenarios delivered_not_seen --offline  # -> DISPUTED (re-check pending)
python -m countersign.scenarios unreadable --offline          # -> INCONCLUSIVE
```
Without `--offline`, the scenarios need `EASYPOST_API_KEY` (test key), `RING_DEVICE_PACKAGE` /
`RING_DEVICE_MOTION` and a Bedrock model. The tracker-to-stream wiring and the scan time are
staged; offline, the frames are synthetic and can never back a claim.

## License
Apache-2.0.
