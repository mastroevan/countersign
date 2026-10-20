# DEVLOG

Unexpected API behavior, timeouts, and SDK bugs. Format per CLAUDE.md:
timestamp, request ID, expected vs actual.

## 2026-10-20 — Review findings fixed (no live API incidents)

No live Ring or Bedrock calls were made in this session, so there are no
request IDs. Defects found by code review and fixed:

- **Ring e2e check failed open.** Expected: only devices with
  `e2e_encryption.enabled == false` are streamed. Actual: a missing or null
  field passed as unencrypted. Now requires an explicit `false`.
- **Synthetic frames were indistinguishable from live ones.** Expected:
  simulation output can never back a claim. Actual: `COUNTERSIGN_OFFLINE_SIMULATION`
  swapped frames silently. Frames/observations now carry `source`, the policy
  excludes synthetic by default, and the approval layer refuses synthetic decisions.
- **Naive watermark timestamps were assumed UTC.** Expected: local-time
  watermarks resolve with the device zone. Actual: shifted by the UTC offset.
  Now uses `COUNTERSIGN_DEVICE_TZ`; with no zone the frame is ignored.
- **`get_camera_frames` fallback was dead code**, and `stop_whep` could raise
  from cleanup. Both fixed.

## 2026-10-20 — `mcp` 2.x removed `mcp.server.fastmcp`

- Request ID: n/a (import-time failure, no network call).
- Expected: `from mcp.server.fastmcp import FastMCP` works with the `mcp`
  package pyproject resolved (2.3.0), as in 1.x examples and CLAUDE.md.
- Actual: `ModuleNotFoundError`; 2.x renamed it to `MCPServer`.
- Resolution: depend on the standalone `fastmcp` package (4.1.3, which runs
  alongside mcp 2.3.0) and drop the direct `mcp` and unused `easypost`
  dependencies. Streamable HTTP initialize with protocol 2025-11-25 is covered
  by `tests/test_mcp.py`. Note `mcp.types.LATEST_PROTOCOL_VERSION` is now
  2026-07-28, newer than the 2025-11-25 in CLAUDE.md.
