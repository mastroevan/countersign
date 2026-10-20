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
