"""
Issuer-health detector tests.

The detector has to distinguish a real outage from an issuer that is simply
busy, and it has to stop flagging once the outage ends. Both directions matter:
a detector that never clears holds retries forever.
"""

from datetime import timedelta

from app.core.clock import BATCH_START, SPIKE_ISSUER, SPIKE_START, iso
from app.core.detector import IssuerHealthDetector


def failure(issuer, at, reason="issuer_down"):
    return {"issuer": issuer, "created_at": iso(at), "error_reason": reason}


def steady_background(issuer="SBI", n=60, spacing_minutes=5):
    """A bank failing at a constant low rate — normal, not an outage."""
    return [
        failure(issuer, BATCH_START - timedelta(hours=6) + timedelta(minutes=i * spacing_minutes))
        for i in range(n)
    ]


def test_a_burst_is_flagged():
    det = IssuerHealthDetector()
    payments = steady_background("HDFC", n=40, spacing_minutes=20)
    burst_at = BATCH_START - timedelta(minutes=20)
    payments += [failure("HDFC", burst_at + timedelta(seconds=i * 10)) for i in range(25)]

    det.load_payments(payments)
    assert det.is_degraded("HDFC", burst_at)


def test_a_steadily_busy_issuer_is_not_flagged():
    """
    Volume alone is not an outage. Scoring each issuer against its own baseline
    is what stops the busiest bank from being permanently "degraded".
    """
    det = IssuerHealthDetector()
    det.load_payments(steady_background("SBI", n=120, spacing_minutes=5))
    assert not det.is_degraded("SBI", BATCH_START)


def test_an_unknown_issuer_is_treated_as_healthy():
    det = IssuerHealthDetector()
    det.load_payments(steady_background())
    assert not det.is_degraded("ICICI", BATCH_START)
    assert not det.is_degraded(None, BATCH_START)


def test_health_is_restored_once_the_outage_is_far_enough_behind():
    det = IssuerHealthDetector()
    burst_at = BATCH_START - timedelta(minutes=30)
    det.load_payments(
        steady_background("HDFC", n=40, spacing_minutes=20)
        + [failure("HDFC", burst_at + timedelta(seconds=i * 10)) for i in range(25)]
    )

    assert det.is_degraded("HDFC", burst_at)
    assert not det.is_degraded("HDFC", burst_at + timedelta(hours=24))


def test_only_infrastructure_failures_count():
    """
    A wave of insufficient-funds declines says something about customers, not
    about the bank's availability, and must not hold retries.
    """
    det = IssuerHealthDetector()
    at = BATCH_START - timedelta(minutes=10)
    det.load_payments([
        failure("HDFC", at + timedelta(seconds=i * 5), reason="insufficient_funds")
        for i in range(50)
    ])
    assert not det.is_degraded("HDFC", at)


def test_ingestion_order_does_not_change_the_verdict():
    payments = (
        steady_background("HDFC", n=40, spacing_minutes=20)
        + [failure("HDFC", BATCH_START - timedelta(minutes=20) + timedelta(seconds=i * 10))
           for i in range(25)]
    )
    forward, backward = IssuerHealthDetector(), IssuerHealthDetector()
    forward.load_payments(payments)
    backward.load_payments(list(reversed(payments)))

    at = BATCH_START - timedelta(minutes=15)
    assert forward.is_degraded("HDFC", at) == backward.is_degraded("HDFC", at)


def test_the_planted_outage_is_still_live_when_the_batch_starts():
    """
    Guards the timing the whole demo depends on. The generator places the
    outage so it straddles the batch boundary; if that drifts, G08 never fires
    during the run and the retry-hold story disappears silently.
    """
    from app.sim.generator import generate_dataset

    det = IssuerHealthDetector()
    det.load_payments(generate_dataset(seed=42)["payments"])

    # Bucket edges are derived from the first failure in the dataset, so the
    # flagged window does not begin exactly at SPIKE_START. What has to hold is
    # that the issuer is still unhealthy when the first ticks run, and healthy
    # again well before the horizon ends.
    assert det.is_degraded(SPIKE_ISSUER, BATCH_START)
    assert det.is_degraded(SPIKE_ISSUER, BATCH_START + timedelta(hours=4))
    assert not det.is_degraded(SPIKE_ISSUER, BATCH_START + timedelta(days=2))

    windows = det._windows[SPIKE_ISSUER]
    assert windows, "the planted outage produced no spike window"
    assert min(w["start"] for w in windows) >= SPIKE_START - timedelta(minutes=10)


def test_health_report_lists_every_issuer_seen():
    det = IssuerHealthDetector()
    det.load_payments(steady_background("SBI") + steady_background("Axis"))
    issuers = {r["issuer"] for r in det.health_report()}
    assert {"SBI", "Axis"} <= issuers
