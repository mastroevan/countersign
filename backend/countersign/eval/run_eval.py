"""Evaluate the vision judge against labeled frames.

Only the judge's observations are scored (is a parcel visible, where). Verdicts
are policy logic and are covered by unit tests.

Run: python -m countersign.eval.run_eval [--labels eval/frames/labels.csv]
     python -m countersign.eval.run_eval --dry-run   # oracle stub, checks plumbing
Needs AWS credentials and BEDROCK_MODEL_ID unless --dry-run.
"""
from __future__ import annotations

import argparse
import csv
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from countersign.aws import make_client
from countersign.policy import Observation
from countersign.vision_judge import judge_frame

# backend/eval/frames/labels.csv, independent of the current directory
DEFAULT_LABELS = Path(__file__).resolve().parents[2] / "eval" / "frames" / "labels.csv"

Judge = Callable[[bytes, str], Observation]  # (jpeg bytes, filename) -> Observation


@dataclass(frozen=True)
class Label:
    filename: str
    parcel_visible: bool
    location: str | None
    source: str = "real"


@dataclass(frozen=True)
class Metrics:
    n: int
    errors: int
    tp: int
    fp: int
    fn: int
    tn: int
    location_correct: int
    location_total: int
    unjudged_negatives: int = 0  # judge errors on frames labeled no-parcel

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if self.tp + self.fp else 0.0

    @property
    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if self.tp + self.fn else 0.0

    @property
    def location_accuracy(self) -> float:
        return self.location_correct / self.location_total if self.location_total else 0.0


def load_labels(path: Path) -> list[Label]:
    with open(path, newline="") as f:
        return [
            Label(
                r["filename"],
                r["parcel_visible"].strip().lower() == "true",
                None if r["location"] in ("", "none") else r["location"],
                r.get("source") or "real",
            )
            for r in csv.DictReader(f)
        ]


def compute_metrics(
    labels: list[Label], predictions: list[Observation | None], min_confidence: float = 0.80
) -> Metrics:
    """A prediction counts as positive only if visible AND confidence >= threshold,
    matching how the policy treats low-confidence frames (ignored)."""
    tp = fp = fn = tn = errors = loc_ok = loc_total = unjudged_neg = 0
    for lab, obs in zip(labels, predictions):
        if obs is None:
            errors += 1
            if lab.parcel_visible:
                fn += 1  # a frame we could not judge is a missed parcel
            else:
                unjudged_neg += 1  # neither a true negative nor a false positive
            continue
        pred = obs.parcel_visible and obs.confidence >= min_confidence
        if lab.parcel_visible and pred:
            tp += 1
            loc_total += 1
            loc_ok += obs.location == lab.location
        elif lab.parcel_visible:
            fn += 1
        elif pred:
            fp += 1
        else:
            tn += 1
    return Metrics(len(labels), errors, tp, fp, fn, tn, loc_ok, loc_total, unjudged_neg)


def evaluate(
    labels: list[Label], frames_dir: Path, judge: Judge, min_confidence: float = 0.80
) -> Metrics:
    preds: list[Observation | None] = []
    for lab in labels:
        try:
            preds.append(judge((frames_dir / lab.filename).read_bytes(), lab.filename))
        except Exception as exc:
            print(f"  {lab.filename}: {type(exc).__name__}: {exc}", file=sys.stderr)
            preds.append(None)
    return compute_metrics(labels, preds, min_confidence)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--labels", type=Path, default=DEFAULT_LABELS)
    ap.add_argument("--min-confidence", type=float, default=0.80)
    ap.add_argument("--min-precision", type=float, default=0.95)
    ap.add_argument("--min-recall", type=float, default=0.90)
    ap.add_argument("--dry-run", action="store_true", help="oracle judge; checks plumbing only")
    ap.add_argument("--real-only", action="store_true", help="skip rows with source=synthetic")
    args = ap.parse_args(argv)

    labels = load_labels(args.labels)
    if args.real_only:
        labels = [x for x in labels if x.source != "synthetic"]
    if not labels:
        print("no labeled frames to evaluate", file=sys.stderr)
        return 2

    by_name = {x.filename: x for x in labels}
    judge: Judge
    if args.dry_run:
        def judge(_: bytes, name: str) -> Observation:
            lab = by_name[name]
            return Observation(lab.parcel_visible, 1.0, lab.location)
    else:
        client = make_client("bedrock-runtime")

        def judge(img: bytes, _: str) -> Observation:
            return judge_frame(client, img)

    m = evaluate(labels, args.labels.parent, judge, args.min_confidence)
    print(f"frames={m.n} errors={m.errors} (unjudged negatives={m.unjudged_negatives})  TP={m.tp} FP={m.fp} FN={m.fn} TN={m.tn}")
    print(f"precision={m.precision:.3f} recall={m.recall:.3f} location_accuracy={m.location_accuracy:.3f}")
    if args.dry_run:
        print("(dry run: oracle predictions, not a model result)")
    ok = m.precision >= args.min_precision and m.recall >= args.min_recall
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
