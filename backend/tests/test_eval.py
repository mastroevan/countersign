from pathlib import Path

from countersign.eval.run_eval import Label, compute_metrics, load_labels, main
from countersign.policy import Observation


def L(visible, loc="porch"):
    return Label("f.jpg", visible, loc if visible else None)


def O(visible, conf=0.95, loc="porch"):
    return Observation(visible, conf, loc)


def test_confusion_matrix_and_location():
    labels = [L(True), L(True, "step"), L(True), L(False), L(False)]
    preds = [O(True), O(True, loc="porch"), O(False), O(True), O(False)]
    m = compute_metrics(labels, preds)
    assert (m.tp, m.fp, m.fn, m.tn) == (2, 1, 1, 1)
    assert m.precision == 2 / 3 and m.recall == 2 / 3
    assert m.location_correct == 1 and m.location_total == 2


def test_low_confidence_counts_as_negative():
    m = compute_metrics([L(True)], [O(True, conf=0.5)])
    assert (m.tp, m.fn) == (0, 1)


def test_judge_errors_are_misses_not_crashes():
    m = compute_metrics([L(True), L(False)], [None, None])
    assert m.errors == 2 and m.fn == 1 and m.tn == 0 and m.fp == 0


def test_empty_metrics_do_not_divide_by_zero():
    m = compute_metrics([], [])
    assert m.precision == 0.0 and m.recall == 0.0 and m.location_accuracy == 0.0


def test_committed_labels_load_and_dry_run_passes(capsys):
    labels = load_labels(Path("eval/frames/labels.csv"))
    assert len(labels) == 12 and all(x.source == "synthetic" for x in labels)
    assert main(["--dry-run"]) == 0
    assert "oracle" in capsys.readouterr().out


def test_real_only_with_no_real_frames_exits_nonzero():
    assert main(["--dry-run", "--real-only"]) == 2


def test_every_frame_is_accounted_for_even_with_judge_errors():
    labels = [L(True), L(True), L(False), L(False), L(False)]
    preds = [O(True), None, None, O(True), O(False)]
    m = compute_metrics(labels, preds)
    assert m.errors == 2 and m.unjudged_negatives == 1
    assert m.tp + m.fp + m.fn + m.tn + m.unjudged_negatives == m.n


def test_default_labels_path_works_from_any_directory(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)
    assert main(["--dry-run"]) == 0
