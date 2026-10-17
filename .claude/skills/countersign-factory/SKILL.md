---
name: countersign-factory
description: Orchestrates full vertical-slice builds for Countersign features (webhook -> WHEP -> Bedrock -> policy -> UI/MCP).
---
Process:
1. Invoke the built-in `Explore` agent to map existing backend routes, schemas, or UI components.
2. Formulate a technical brief covering:
   - Schema updates (DynamoDB ledger, S3 packet structure)
   - Endpoint or tool contract (`/webhooks/easypost`, MCP tool parameters)
   - Test cases against `ring-sandbox`
3. PAUSE FOR HUMAN APPROVAL: Confirm architecture and trade-offs.
4. Invoke `backend-builder` to implement services, policy rules, and unit tests.
5. Invoke `frontend-builder` to implement UI tiles, split screens, and MCP client actions.
6. Invoke `eval-verifier` to run pytest and verify precision/recall across `eval/frames/labels.csv`.
7. If any SDK bugs, quota issues, or token lifetime limits occurred during the build, invoke `friction-logger` to append entries to `docs/FRICTION.md`.
8. Invoke `implementation-validator` to ensure deterministic execution and rule compliance.
9. Present the summary and git diff for final review.