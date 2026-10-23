# Integration notes and product feedback

What it was like to build against each tool, API and SDK. Everything here comes from
`docs/DEVLOG.md` and the code. Services marked **not run live** were developed against
their documentation and exercised only through tests with mocks; no live behavior is
claimed for them.

| Service | Job in Countersign | Status |
|---|---|---|
| Ring Developer Playground / Partner API | Device discovery, `e2e_encryption.enabled` check, WHEP live view | Not run live |
| Amazon Bedrock Converse (vision) | Reports parcel visibility only; never a verdict | Not run live |
| Amazon S3 | Approval-gated evidence packet (manifest + unmodified frames, SSE, SHA-256) | Not run live |
| EasyPost (test mode) | `tracker.updated` webhook and tracker lookup | Not run live |
| FastMCP / MCP 2025-11-25 | Self-hosted MCP server over Streamable HTTP | Run (tests + browser client) |
| `@modelcontextprotocol/sdk` | The `/alexa` page as an MCP client | Run |

Not used: Strands Agents, Bedrock AgentCore, DynamoDB (the ledger is in memory), Kiro.

## Ring Developer Playground and Partner API
- **Worked (by design):** bearer-token calls, `GET /v1/devices`, and WHEP sessions map
  cleanly onto a small async client. The explicit `e2e_encryption.enabled` flag makes a
  fail-closed privacy check easy.
- **Needs work:** the 30-minute token forces a fresh token per session; the burned-in
  local-time watermark has no zone (we added `COUNTERSIGN_DEVICE_TZ`), so capture time as
  response metadata would remove an OCR step; simulated streams cannot show a parcel
  arriving on demand, so scenarios are staged by binding a tracker to a stream.

## Amazon Bedrock (Converse, vision)
- **Design benefit:** forced tool use (`toolChoice` on one `report_observation` tool)
  gives strict JSON with no free text, so the policy owns every verdict. Response
  metadata gives a per-call audit trail (model ID, request ID, latency).
- **Friction:** `boto3` raises `NoRegionError` with no configured region, so client
  creation falls back to `us-east-1`. Availability of vision models by region and
  inference-profile ID was not tested.

## Amazon S3
- Packets use `ServerSideEncryption` and `ChecksumAlgorithm=SHA256`; frames are stored
  byte-for-byte so the watermark survives, and a manifest hash commits to every frame.

## EasyPost (test mode)
- Test trackers and `tracker.updated` webhooks cover the "delivered" trigger without a
  shipment; HMAC verification is simple. Test mode sends one event in one status, so the
  full scan timeline needs staging.

## FastMCP and the MCP specification
- **Worked:** Streamable HTTP mounted in FastAPI at `/mcp/`; `initialize` with protocol
  `2025-11-25` is tested; the browser client completes `initialize`, `tools/list`, `tools/call`.
- **Needs work:** `mcp` 2.x removed `mcp.server.fastmcp` while most guides still use it
  (see `docs/FRICTION.md` FL-01); `LATEST_PROTOCOL_VERSION` is now `2026-07-28`, newer than
  2025-11-25; mounting under `/mcp` caused a trailing-slash redirect that broke the browser
  client (fixed in `f3eb0c9`).

## Development process
Code review passes found real defects that are logged in the DEVLOG: a fail-open
encryption check, naive watermark timestamps read as UTC, synthetic frames passing as live,
a stale re-check timer that wiped approvals, parcels seen before the scan counting as proof,
and a stub judge that could run on live frames.
