# Countersign — Amazon Developer Hackathon Project

## Stack
- Backend: Python 3.11+, FastAPI, Uvicorn, aiortc, boto3 (Bedrock Converse), Strands Agents SDK, bedrock-agentcore, FastMCP (Streamable HTTP, spec 2025-11-25)
- Frontend: Next.js 14/15 (App Router), TypeScript, Tailwind CSS, @modelcontextprotocol/sdk
- Testing: pytest, pytest-asyncio, ring-sandbox emulator

## Core Commands
- Backend Dev: `cd backend && uvicorn countersign.main:app --reload --port 8000`
- Frontend Dev: `cd web && npm run dev`
- Tests: `cd backend && pytest tests/`
- Eval Suite: `cd backend && python -m countersign.eval.run_eval`
- Type Check: `cd web && npm run typecheck && cd ../backend && mypy countersign`

## Architecture & Guardrails
- **Deterministic Policy**: Bedrock Converse ONLY answers "is a parcel visible, where, confidence, watermark timestamp". All VERIFIED, DISPUTED, and INCONCLUSIVE decisions are calculated in `policy.py` via standard Python logic. Never let the LLM produce final verdicts directly.
- **Privacy & Compliance**: Do not identify human faces or vehicles. Descriptions apply strictly to the step/porch and parcels.
- **Ring Watermark**: Do not treat the embedded Ring watermark (timestamp/device ID) as parcel evidence, but preserve it in evidence frames for auditability.
- **Device Checks**: Verify `e2e_encryption.enabled == false` before opening WHEP live sessions.
- **Approval Gates**: Claims drafting and S3 evidence packets require explicit human approval (`requires_approval: true`).

## Hackathon Output Contracts
- Any unexpected API behavior, timeout, or SDK bug encountered must be logged with timestamp, request ID, expected vs actual to `docs/DEVLOG.md`.
