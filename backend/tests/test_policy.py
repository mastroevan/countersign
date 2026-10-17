from datetime import datetime, timedelta, timezone

from countersign.policy import Observation, PolicyConfig, Verdict, decide

T0 = datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc)


def obs(visible=True, conf=0.95, loc="porch", dt=timedelta(minutes=2)):
    return Observation(visible, conf, loc, T0 + dt)


def test_verified_single_confident_positive():
    d = decide([obs()], T0)
    assert d.verdict is Verdict.VERIFIED
    assert d.requires_approval


def test_disputed_needs_two_negatives():
    assert decide([obs(False)], T0).verdict is Verdict.INCONCLUSIVE
    d = decide([obs(False), obs(False, dt=timedelta(minutes=4))], T0)
    assert d.verdict is Verdict.DISPUTED


def test_no_observations_inconclusive():
    assert decide([], T0).verdict is Verdict.INCONCLUSIVE


def test_low_confidence_ignored():
    d = decide([obs(conf=0.5)], T0)
    assert d.verdict is Verdict.INCONCLUSIVE
    assert d.considered_frames == 0


def test_conflicting_evidence_inconclusive():
    d = decide([obs(True), obs(False)], T0)
    assert d.verdict is Verdict.INCONCLUSIVE


def test_out_of_window_ignored():
    early = obs(dt=-timedelta(minutes=6))
    late = obs(dt=timedelta(minutes=31))
    assert decide([early, late], T0).verdict is Verdict.INCONCLUSIVE


def test_window_boundaries_inclusive():
    assert decide([obs(dt=-timedelta(minutes=5))], T0).verdict is Verdict.VERIFIED
    assert decide([obs(dt=timedelta(minutes=30))], T0).verdict is Verdict.VERIFIED


def test_missing_watermark_never_counts():
    o = Observation(True, 0.99, "porch", None)
    assert decide([o], T0).verdict is Verdict.INCONCLUSIVE


def test_naive_vs_aware_timestamp_unusable():
    o = Observation(True, 0.99, "porch", datetime(2026, 10, 15, 12, 1))
    assert decide([o], T0).verdict is Verdict.INCONCLUSIVE


def test_disallowed_location_not_positive():
    assert decide([obs(loc="driveway")], T0).verdict is Verdict.INCONCLUSIVE


def test_custom_config():
    cfg = PolicyConfig(min_negative_frames=1)
    assert decide([obs(False)], T0, cfg).verdict is Verdict.DISPUTED
