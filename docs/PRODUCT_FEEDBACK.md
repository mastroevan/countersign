# Product feedback

One section per tool, API or SDK Countersign uses. Each answers: what worked,
what needs work, onboarding, would I build with it again.

> **Draft status (2026-10-21).** Everything below is grounded in `docs/DEVLOG.md`
> and the code. Lines marked **[FILL]** need a number or observation from a live
> run that has not happened yet. DEVLOG records that no live Ring or Bedrock call
> had been made as of 2026-10-20, so do not submit this with any **[FILL]** left in
> it, and do not replace one with a guess.

## Summary: what each service does in Countersign

| Service | Job in the product | Used live? |
|---|---|---|
| Ring Developer Playground / Partner API (`api.amazonvision.com`) | Device discovery, `e2e_encryption.enabled` check, WHEP live-view session, frames from Package/Motion streams | **[FILL]** |
| Amazon Bedrock Converse (vision) | Reports only: parcel visible?, where, confidence, watermark time. Never a verdict | **[FILL]** |
| Amazon S3 | Approval-gated evidence packet (manifest + unmodified frames, SSE, SHA-256 checksums) | **[FILL]** |
| EasyPost (test mode) | `tracker.updated` webhook and tracker lookup by tracking code | **[FILL]** |
| FastMCP / MCP spec 2025-11-25 | Self-hosted Alexa+-style MCP server over Streamable HTTP | Yes (tests + browser client) |
| `@modelcontextprotocol/sdk` (TypeScript) | The `/alexa` page acting as the MCP client | Yes |
| aiortc | Server-side WHEP receive, JPEG frame grab | **[FILL]** against real Ring |

Not used, so not claimed: Strands Agents SDK, Bedrock AgentCore, DynamoDB (the
ledger is in memory), Kiro. Do not list them in the Devpost text unless that changes.

---

## Ring Developer Playground and Partner API

- **Worked:** The API shape (bearer token, `GET /v1/devices` with status and
  configurations, WHEP sessions under `/media/streaming/whep/sessions`) maps cleanly
  onto a small async client, and the explicit `e2e_encryption.enabled` flag makes a
  fail-closed privacy check easy to write. **[FILL: what worked when run live]**
- **Needs work:**
  - The Playground token lasts 30 minutes, so a demo or recording session needs a
    fresh token per take. A refresh path or longer-lived test token would help.
  - A burned-in local-time watermark with no zone forced us to add
    `COUNTERSIGN_DEVICE_TZ`. Exposing the capture time as response metadata would
    remove an OCR step and a failure mode.
  - Simulated streams cannot show a parcel arriving or leaving on demand, so we stage
    scenarios by binding a tracker to a stream. A scriptable Playground scenario
    ("parcel appears at T+30s") would make delivery demos honest and repeatable.
  - **[FILL: any live error codes, latency to first frame, ICE/WHEP quirks]**
- **Onboarding:** **[FILL: minutes from sign-in to first live-view frame, and the
  step that took longest]**
- **Build again?** Yes, if I can read real frame timestamps from the API instead of
  the image. **[FILL after live run]**

## Amazon Bedrock (Converse API, vision)

- **Worked:** Forced tool use (`toolChoice` on one `report_observation` tool) gives a
  strict JSON schema with no free text, which is what lets the policy, not the model,
  own every verdict. The response `ResponseMetadata.RequestId` and `usage` make a
  per-call audit trail (model ID, request ID, latency) easy to show in the trace
  panel. **[FILL: model ID used, typical latency, accuracy on real Playground frames]**
- **Needs work:** `boto3` raises `NoRegionError` when no region is configured, so we
  wrap client creation with a `us-east-1` fallback. A clearer first-run error, or a
  documented default, would save a step. **[FILL: quota or access issues, if any]**
- **Onboarding:** **[FILL: minutes to first successful vision call]**
- **Build again?** Yes for perception ("is a parcel visible, where, how sure").
  No for judgment; we deliberately keep verdicts out of the model. **[FILL]**

## Amazon S3

- **Worked:** `put_object` with `ServerSideEncryption` and `ChecksumAlgorithm=SHA256`
  fits an evidence packet: frames are stored byte-for-byte so the Ring watermark is
  preserved, and a manifest hash commits to every frame. **[FILL: confirm against a
  real bucket]**
- **Needs work:** **[FILL]**
- **Onboarding:** **[FILL]**
- **Build again?** Yes. **[FILL]**

## EasyPost (test mode)

- **Worked:** Test trackers and `tracker.updated` webhooks cover the "carrier says
  delivered" trigger without a real shipment. HMAC verification
  (`X-Hmac-Signature: hmac-sha256-hex=...`) is simple to implement. **[FILL: confirm
  with a real tunnel]**
- **Needs work:** Test mode sends a single event in one status, so showing the
  full scan timeline needs staging. **[FILL: any observed payload surprises]**
- **Onboarding:** **[FILL]**
- **Build again?** Yes. **[FILL]**

## FastMCP and the MCP specification (2025-11-25)

All of this is from `docs/DEVLOG.md` (2026-10-20), not memory.

- **Worked:** Streamable HTTP mounted inside FastAPI at `/mcp/`; `initialize` with
  protocol `2025-11-25` is covered by `tests/test_mcp.py`; the browser client
  completes `initialize`, `tools/list` and `tools/call`.
- **Needs work:**
  - `mcp` 2.x removed `mcp.server.fastmcp` (`ModuleNotFoundError`; renamed
    `MCPServer`), while most examples and guides still use the 1.x import. We moved to
    the standalone `fastmcp` package (4.1.3). Release notes or a deprecation shim
    would have saved time. See `docs/FRICTION.md` FL-01.
  - `mcp.types.LATEST_PROTOCOL_VERSION` is `2026-07-28`, newer than the 2025-11-25
    named in the hackathon rules, so it is easy to wonder which version a server
    should claim.
  - Mounting the app under `/mcp` produced a trailing-slash redirect that broke the
    browser client (fixed in commit `f3eb0c9`).
- **Onboarding:** **[FILL: minutes from empty file to first `tools/call`]**
- **Build again?** Yes.

## TypeScript MCP SDK (`@modelcontextprotocol/sdk`)

- **Worked:** `StreamableHTTPClientTransport` negotiates the protocol version and
  lets a web page act as the client, so the Alexa+ simulator page makes real
  JSON-RPC calls rather than canned ones.
- **Needs work:** **[FILL: browser/CORS notes; the backend needed
  `expose_headers` and a trailing-slash fix]**
- **Build again?** Yes.

## aiortc (WHEP receive)

- **Worked / needs work / onboarding:** **[FILL: only after the live WHEP run; the
  tests use mocks]**

## Claude Code (development tool)

- Used to build the backend, frontend and tests, and to run code review passes that
  found real defects (fail-open encryption check, naive watermark timestamps,
  synthetic frames passing as live; see DEVLOG 2026-10-20). **[FILL: your own
  assessment]**
