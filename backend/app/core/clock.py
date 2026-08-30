"""
Deterministic simulation clock.

Why this module exists
----------------------
Half of the policy engine is time-dependent: quiet hours (G02), the frequency
cap (G03), the cooldown (G05) and issuer-health windows (G08) all read "now".
If "now" is `datetime.now()`, the same repo produces different numbers
depending on what time of day the judge runs `make demo` — run it at 23:00 IST
and G02 blocks every single outreach.

So RecoverOS never calls `datetime.now()` in the decision path. The dataset is
generated relative to a fixed epoch and the batch is a discrete-event
simulation stepping over a fixed horizon. Same seed, same clock, same numbers,
on any machine, at any hour.

Timeline
--------
    DATA_EPOCH                     BATCH_START                 BATCH_END
        |<------ 3 days of ------->|<------ 7 days of -------->|
        |     failed payments      |   recovery simulation     |
                                   ^
                          issuer spike sits here,
                          straddling the boundary, so the
                          detector is actually degraded when
                          the first ticks run
"""

# Re-exported deliberately: the rest of the codebase reaches for time through
# this module (`clock.datetime`, `clock.timedelta`) rather than importing
# datetime directly, which keeps `datetime.now()` from creeping back into the
# decision path unnoticed.
from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))

# Anchor for the whole simulation. Chosen, not discovered — every timestamp in
# the repo derives from it.
DATA_EPOCH = datetime(2026, 8, 29, 0, 0, 0, tzinfo=timezone.utc)

# How much payment history the dataset covers before the agent wakes up.
DATA_WINDOW_HOURS = 72

# The moment the recovery agent starts working.
BATCH_START = DATA_EPOCH + timedelta(hours=DATA_WINDOW_HOURS)

# How long the agent is allowed to work, and how finely we step through it.
HORIZON_HOURS = 168  # 7 days
TICK_HOURS = 2
TICK_COUNT = HORIZON_HOURS // TICK_HOURS  # 84 ticks

BATCH_END = BATCH_START + timedelta(hours=HORIZON_HOURS)

# The issuer-outage window. Deliberately placed so it ends just after the batch
# begins: the first few ticks see a degraded issuer, then it recovers and the
# held retries release. That transition is the point.
SPIKE_DURATION_MINUTES = 40
SPIKE_START = BATCH_START - timedelta(minutes=SPIKE_DURATION_MINUTES)
SPIKE_END = BATCH_START
SPIKE_ISSUER = "HDFC"


def ticks():
    """Yield (tick_index, utc_datetime) for every step of the simulation."""
    for i in range(TICK_COUNT):
        yield i, BATCH_START + timedelta(hours=i * TICK_HOURS)


def to_ist(dt_utc: datetime) -> datetime:
    """Convert a UTC datetime to IST. Naive input is assumed to be UTC."""
    if dt_utc.tzinfo is None:
        dt_utc = dt_utc.replace(tzinfo=timezone.utc)
    return dt_utc.astimezone(IST)


def ist_hour(dt_utc: datetime) -> int:
    """IST hour-of-day (0-23) for a UTC instant. Used by the quiet-hours gate."""
    return to_ist(dt_utc).hour


def iso(dt: datetime) -> str:
    """Canonical timestamp string. One format everywhere, including the ledger."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()
