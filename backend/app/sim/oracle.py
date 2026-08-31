"""
The outcome oracle.

This is the honest part of the project, so it gets said plainly: **the money is
simulated.** No real customer was messaged and no real payment was recovered.
What is real is the decision logic, the guardrails, the audit trail and the
measurement method. The oracle exists so those can be evaluated end-to-end.

Rules the oracle plays by:

* No decision module reads it. The classifier, the ladder, the policy engine,
  the detector and the live webhook handler do not import it, so nothing in
  this file can change what the agent chooses to do.

  The orchestrator does import it, because something has to record what
  happened, and it calls only the four functions that report an outcome -
  after it has already decided and acted, exactly as it would ask a payment
  gateway. `tests/test_sensitivity.py` pins both halves of that boundary.

  This distinction is load-bearing, not pedantry: it is what makes the
  sensitivity sweep valid. Because the decisions cannot depend on these
  numbers, changing them re-decides outcomes over a fixed run rather than
  producing a different run.
* It is seeded per case, so the same case with the same treatment always
  resolves the same way. Re-running the batch cannot fish for a better number.
* It uses a local RNG. Calling `random.seed()` globally would make every other
  seeded component depend on the order the oracle happened to be called in.
* Its base rates are written down and justified in `docs/assumptions.md`,
  including the control-arm rates. If you think a number is wrong, you can
  change one line and re-run.
"""

import hashlib
import random
from typing import Optional

# P(recovery | recovery_class) over the whole observation window with no
# intervention at all — the customer comes back on their own. This is the
# number that makes the headline honest: without it, natural recovery gets
# credited to the agent.
NO_INTERVENTION_BASELINE = {
    "AUTO_RETRY": 0.29,
    "RETRY_TIMED": 0.24,
    "SWITCH_METHOD": 0.11,
    "NUDGE_CUSTOMER": 0.14,
    # An abandoned cart is the highest-intent, lowest-commitment state in the
    # dataset: a meaningful share of people come back unprompted within a week.
    # It is also the class where the agent has the least to add, because there
    # is no failure to fix.
    "CHECKOUT_ABANDONED": 0.17,
    # Almost nobody re-authorises a lapsed mandate on their own — they either
    # do not notice the subscription stopped, or they meant it to.
    "MANDATE_REPAIR": 0.04,
    "RECEIVABLE_CHASE": 0.09,
    "MANUAL_REVIEW": 0.02,
    "DEAD": 0.00,
}

# Additional probability contributed by each rung, on top of the baseline.
#
# These are *marginal* lifts, not per-attempt success rates, and that
# distinction is the whole model. Drawing an independent success roll per touch
# would give a three-touch case three chances at recovery while a control case
# got one — the treatment arm would win on arithmetic before the agent did
# anything, and the lift would be an artefact of the simulation rather than a
# measurement of the policy. Instead each case gets exactly one random draw and
# each delivered touch lowers the bar it has to clear.
TIER_MARGINAL_LIFT = {
    ("AUTO_RETRY", 0): 0.22,   # the issuer recovered and the retry simply works
    ("AUTO_RETRY", 1): 0.06,
    ("AUTO_RETRY", 2): 0.03,

    ("RETRY_TIMED", 0): 0.07,  # retrying before payday rarely helps on its own
    ("RETRY_TIMED", 1): 0.11,
    ("RETRY_TIMED", 2): 0.05,

    ("SWITCH_METHOD", 1): 0.17,  # telling them *what* to fix is the whole value
    ("SWITCH_METHOD", 2): 0.06,

    ("NUDGE_CUSTOMER", 1): 0.10,
    ("NUDGE_CUSTOMER", 2): 0.05,

    # A cart reminder converts, but modestly — the customer already chose not
    # to finish once, and nothing about their situation has changed.
    ("CHECKOUT_ABANDONED", 1): 0.09,
    ("CHECKOUT_ABANDONED", 2): 0.03,

    # The largest marginal lift in the model, and the one the old DEAD
    # classification was throwing away: the customer usually has no idea their
    # mandate lapsed, so telling them is most of the work.
    ("MANDATE_REPAIR", 1): 0.19,
    ("MANDATE_REPAIR", 2): 0.07,

    ("RECEIVABLE_CHASE", 1): 0.07,
    ("RECEIVABLE_CHASE", 2): 0.06,
    ("RECEIVABLE_CHASE", 3): 0.15,   # a voice call is worth what it costs

    ("MANUAL_REVIEW", 4): 0.02,
}

# No amount of contact makes recovery certain. Past this, extra touches buy
# irritation rather than revenue.
MAX_RECOVERY_PROBABILITY = 0.85

# P(customer presses 1 and commits to a date | they answered a voice call)
PROMISE_RATE = 0.38
# P(they actually keep that promise)
PROMISE_KEPT_RATE = 0.61


def _roll(*parts) -> float:
    """A deterministic uniform draw keyed to whatever identifies this event."""
    seed_str = "|".join(str(p) for p in parts)
    seed_int = int(hashlib.sha256(seed_str.encode()).hexdigest()[:16], 16)
    return random.Random(seed_int).random()


def recovery_draw(case_id: str) -> float:
    """
    The one random number that decides this case, fixed at generation time.

    A case recovers when its cumulative recovery probability rises above this
    draw. Both arms use the same draw, so treatment and control differ only by
    how much probability the interventions added — which is exactly the
    quantity the experiment is trying to measure.
    """
    return _roll(case_id, "recovery")


def cumulative_probability(recovery_class: str, tiers_delivered) -> float:
    """Baseline plus the marginal lift of every touch actually delivered."""
    p = NO_INTERVENTION_BASELINE.get(recovery_class, 0.0)
    for tier in tiers_delivered:
        p += TIER_MARGINAL_LIFT.get((recovery_class, tier), 0.0)
    return min(p, MAX_RECOVERY_PROBABILITY)


def determine_outcome(case_id: str, recovery_class: str,
                      tiers_delivered=(), arm: str = "treatment") -> bool:
    """
    Has this case recovered, given everything delivered to it so far?

    Monotonic by construction: more touches can only lower the bar, never raise
    it, so a case can never "un-recover" and the sequence of checks over a run
    is consistent.
    """
    tiers = () if arm == "control" else tuple(tiers_delivered)
    return recovery_draw(case_id) < cumulative_probability(recovery_class, tiers)


def makes_promise(case_id: str, tier: int) -> bool:
    """On a voice call, does the customer commit to a payment date?"""
    return _roll(case_id, tier, "promise") < PROMISE_RATE


def keeps_promise(case_id: str) -> bool:
    """Having promised, do they pay by the date they gave?"""
    return _roll(case_id, "promise_kept") < PROMISE_KEPT_RATE


def control_resolution_tick(case_id: str, tick_count: int) -> int:
    """
    When, inside the observation window, an untouched case comes back on its
    own. Spread out rather than all at the end, so the control arm behaves like
    a population rather than a step function.
    """
    return int(_roll(case_id, "control_tick") * tick_count)
