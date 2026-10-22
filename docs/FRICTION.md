# Friction log

Entries follow the hackathon format. Only integration obstacles that actually
happened belong here; our own bugs stay in `docs/DEVLOG.md`.

## FL-01: `mcp` 2.x removed `mcp.server.fastmcp`

- Tool / version: `mcp` 2.3.0 (resolved by pyproject), `fastmcp` 4.1.3
- Task attempted: Stand up the self-hosted MCP server over Streamable HTTP.
- Steps taken:
  1. Followed 1.x-style examples: `from mcp.server.fastmcp import FastMCP`.
  2. Installed with the then-current `mcp` dependency (2.3.0).
  3. Imported the module.
- Expected: The import works, as in 1.x examples and the project spec.
- Actual: `ModuleNotFoundError`. 2.x renamed the class to `MCPServer`. Import-time
  failure, so no request ID.
- Severity: minor
- Workaround: Depend on standalone `fastmcp` (4.1.3, runs alongside mcp 2.3.0); drop
  the direct `mcp` and unused `easypost` dependencies.
- Suggestion: Keep a deprecated `mcp.server.fastmcp` alias that raises an
  explanatory error pointing at `MCPServer` / `fastmcp`, and add the rename to the
  top of the 2.x migration notes. Also state in docs which protocol version
  `LATEST_PROTOCOL_VERSION` (now 2026-07-28) a server should advertise relative to
  2025-11-25.
- Evidence: DEVLOG 2026-10-20 "`mcp` 2.x removed `mcp.server.fastmcp`"; commit `4ea1258`.

<!--
Add entries here ONLY as they happen during the live Ring / Bedrock / EasyPost run.
Candidates the strategy doc flagged but that have not occurred: Playground token
expiry mid-take, WHEP/ICE behavior, Bedrock quota, EasyPost single-event test mode.
-->
