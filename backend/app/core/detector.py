"""
Issuer-health detection.

The signal we care about: is a bank or gateway failing right now at a rate that
is abnormal *for that bank*? A fixed threshold cannot answer that — HDFC's
normal volume is not Kotak's. So we bucket each issuer's infrastructure
failures into short windows, and flag a window whose count is a large number of
standard deviations above that issuer's own mean.

Why it matters commercially: retrying into a dead issuer burns the case's
attempt budget on requests that cannot succeed. Holding those retries until the
issuer recovers is worth more than any message we could send.

This is statistics in Python, not a model call. It is also the one place the
system decides something about the *world* rather than about a single case.
"""

import statistics
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Iterable, Optional

# Failures that indicate the far end is broken — as opposed to the customer
# not having money, or typing the wrong VPA.
INFRA_FAILURE_REASONS = {"issuer_down", "gateway_technical_error", "payment_timeout"}

BUCKET_MINUTES = 10
Z_THRESHOLD = 2.5
MIN_FAILURES_IN_BUCKET = 4

# Once an issuer is flagged, treat it as unhealthy for a while after the last
# bad bucket. Recovery is not instantaneous and flapping in and out of "healthy"
# every ten minutes would release retries into a still-broken bank.
DEGRADED_TAIL_HOURS = 6


def _parse(ts) -> datetime:
    if isinstance(ts, datetime):
        return ts
    return datetime.fromisoformat(ts)


class IssuerHealthDetector:
    def __init__(self, bucket_minutes: int = BUCKET_MINUTES,
                 z_threshold: float = Z_THRESHOLD,
                 min_failures: int = MIN_FAILURES_IN_BUCKET,
                 tail_hours: int = DEGRADED_TAIL_HOURS):
        self.bucket_minutes = bucket_minutes
        self.z_threshold = z_threshold
        self.min_failures = min_failures
        self.tail = timedelta(hours=tail_hours)

        self._buckets = defaultdict(lambda: defaultdict(int))  # issuer -> bucket_idx -> count
        self._origin: Optional[datetime] = None
        self._windows = defaultdict(list)   # issuer -> [(start, end, count, z)]
        self._stats = {}                    # issuer -> (mean, stdev, n_buckets)

    # ------------------------------------------------------------------ ingest
    def reset(self):
        self._buckets.clear()
        self._windows.clear()
        self._stats.clear()
        self._origin = None

    def record_failure(self, issuer: str, timestamp, error_reason: str):
        if not issuer or error_reason not in INFRA_FAILURE_REASONS:
            return
        ts = _parse(timestamp)
        if self._origin is None or ts < self._origin:
            self._origin = ts
        # Raw timestamps here, bucketed in _rebuild — that keeps ingestion
        # order-independent and lets us re-bucket at a different width later.
        self._buckets[issuer][ts] += 1

    def load_payments(self, payments: Iterable[dict]):
        """Feed the whole payment history in one pass. Order does not matter."""
        self.reset()
        for p in payments:
            self.record_failure(p.get("issuer"), p.get("created_at"), p.get("error_reason"))
        self._rebuild()

    # ------------------------------------------------------------------ analyse
    def _rebuild(self):
        """Bucket the raw failures and z-score each issuer against itself."""
        self._windows.clear()
        self._stats.clear()
        if self._origin is None:
            return

        width = timedelta(minutes=self.bucket_minutes)
        for issuer, raw in self._buckets.items():
            counts = defaultdict(int)
            for ts, n in raw.items():
                idx = int((ts - self._origin) / width)
                counts[idx] += n
            if not counts:
                continue

            span = max(counts) + 1
            series = [counts.get(i, 0) for i in range(span)]
            mean = statistics.fmean(series)
            stdev = statistics.pstdev(series) if len(series) > 1 else 0.0
            self._stats[issuer] = (mean, stdev, len(series))

            for idx, n in sorted(counts.items()):
                if n < self.min_failures:
                    continue
                z = (n - mean) / stdev if stdev > 0 else float("inf")
                if z >= self.z_threshold:
                    start = self._origin + idx * width
                    self._windows[issuer].append({
                        "start": start,
                        "end": start + width,
                        "count": n,
                        "z": round(z, 2) if z != float("inf") else None,
                    })

    # ------------------------------------------------------------------ query
    def is_degraded(self, issuer: Optional[str], at) -> bool:
        if not issuer or issuer not in self._windows:
            return False
        t = _parse(at)
        return any(w["start"] <= t <= w["end"] + self.tail for w in self._windows[issuer])

    def degraded_until(self, issuer: str) -> Optional[datetime]:
        wins = self._windows.get(issuer)
        if not wins:
            return None
        return max(w["end"] for w in wins) + self.tail

    def health_report(self, at=None) -> list:
        """Per-issuer status, for the dashboard's issuer strip."""
        out = []
        for issuer in sorted(set(self._buckets) | set(self._windows)):
            mean, stdev, n = self._stats.get(issuer, (0.0, 0.0, 0))
            wins = self._windows.get(issuer, [])
            peak = max((w["count"] for w in wins), default=0)
            out.append({
                "issuer": issuer,
                "degraded": self.is_degraded(issuer, at) if at else bool(wins),
                "spike_windows": len(wins),
                "peak_failures_in_window": peak,
                "baseline_mean": round(mean, 2),
                "baseline_stdev": round(stdev, 2),
                "degraded_until": (
                    self.degraded_until(issuer).isoformat() if wins else None
                ),
            })
        return out


# Module-level instance used by the policy engine. The orchestrator loads it
# from the payment history before a run.
detector = IssuerHealthDetector()
