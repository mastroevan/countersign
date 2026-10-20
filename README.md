# countersign
Hackathon project: verify carrier "delivered" scans against doorbell-camera evidence.

## Backend setup
```bash
cd backend
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
pytest tests/ && mypy countersign
uvicorn countersign.main:app --reload --port 8000
```

Environment: `RING_ACCESS_TOKEN`, `BEDROCK_MODEL_ID`, `COUNTERSIGN_DEVICE_TZ`
(IANA zone of the camera's watermark, e.g. `America/New_York`),
`EASYPOST_WEBHOOK_SECRET` (enforces HMAC when set), `COUNTERSIGN_EVIDENCE_BUCKET`,
`COUNTERSIGN_OFFLINE_SIMULATION=true` (synthetic frames; can never back a claim).
