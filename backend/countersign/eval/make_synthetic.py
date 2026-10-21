"""Generate a small labeled synthetic frame set for harness plumbing tests.

Synthetic frames only prove the eval harness works; real precision/recall
needs real Ring captures added to ``eval/frames/`` and ``labels.csv``.

Run: python -m countersign.eval.make_synthetic
"""
from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path

from countersign.frames import create_synthetic_frame

FRAMES_DIR = Path(__file__).resolve().parents[2] / "eval" / "frames"
CASES = [
    # (parcel_visible, location)
    (True, "porch"),
    (True, "step"),
    (False, "none"),
]


def main() -> None:
    FRAMES_DIR.mkdir(parents=True, exist_ok=True)
    rows = []
    base = datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc)
    for i, (visible, loc) in enumerate(CASES * 4):
        name = f"synthetic_{i:02d}.jpg"
        (FRAMES_DIR / name).write_bytes(
            create_synthetic_frame(
                has_parcel=visible,
                parcel_location="step" if loc == "step" else "porch",
                watermark_time=base.replace(minute=i),
            )
        )
        rows.append({"filename": name, "parcel_visible": str(visible).lower(), "location": loc, "source": "synthetic"})
    with open(FRAMES_DIR / "labels.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["filename", "parcel_visible", "location", "source"])
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {len(rows)} frames to {FRAMES_DIR}")


if __name__ == "__main__":
    main()
