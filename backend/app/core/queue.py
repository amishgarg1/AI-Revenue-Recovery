"""
The human-review queue, and the economics of having one.

`MANUAL_REVIEW` is the class for cases the agent must never contact
automatically: a risk block, an account hold, anything where an automated
message would be the wrong move. The ladder routes them to Tier 4 - a person -
and until now that is where they stopped. They were marked, billed at fifty
rupees of somebody's attention, and then nothing. No queue, no way to work
them, no way to close one.

That is the gap this module fills, and it is the most expensive gap in the
system: Tier 4 is 89% of total spend.

The finding this surfaces, which is not the one we used to state
--------------------------------------------------------------
The evaluation shows this lane's confidence interval includes zero, and both
`future-scope.md` and the video script drew the conclusion that routing to a
person "is not paying for itself". That is an overreach, and computing it
properly says so:

    34 treatment cases, 9 control
    agent time spent          Rs 1,700
    expected incremental      Rs 4,541   (2% marginal lift on Rs 2.27 L)
    to detect a 2% lift       387 cases per arm

In expectation the lane looks *worth it*. What is true is that it cannot be
measured at this size - 34 against 9 cannot distinguish a two-point lift from
nothing. "We cannot tell, and here is what it would take to find out" is a
different and more defensible claim than "it loses money".

What is separately true is that below a break-even amount a call cannot pay
back whatever its lift is, and those cases are worth closing regardless of the
sample size. That threshold is computed rather than asserted.
"""

from typing import List, Optional

from sqlalchemy.orm import Session

from app.analytics.experiment import lift_ci, required_n_per_arm
from app.core import config
from app.models import Case
from app.sim import oracle

# Terminal states an operator has already dealt with, or the batch closed.
WORKED_STATES = {"RECOVERED", "CLOSED"}

HUMAN_TIER = 4
REVIEW_CLASS = "MANUAL_REVIEW"


def break_even_paise(recovery_class: str = REVIEW_CLASS,
                     tier: int = HUMAN_TIER,
                     policy=None) -> Optional[int]:
    """
    The amount below which this rung cannot pay for itself.

    Cost divided by the rung's marginal lift: at fifty rupees and a two percent
    lift, a call needs Rs 2,500 at risk before its expected return covers it.
    Independent of sample size - a case below this is a bad idea however many
    of them you have.

    None when the rung has no modelled lift, because then there is no threshold
    to compute rather than a threshold of zero.
    """
    policy = policy or config.active()
    cost = policy.tier_cost_paise.get(tier, 0)
    lift = oracle.TIER_MARGINAL_LIFT.get((recovery_class, tier), 0.0)
    if lift <= 0:
        return None
    return int(cost / lift)


def _row(case: Case, threshold: Optional[int]) -> dict:
    return {
        "case_id": case.case_id,
        "entity_type": case.entity_type,
        "entity_id": case.entity_id,
        "customer_id": case.customer_id,
        "amount_at_risk_paise": case.amount_at_risk_paise,
        "rule_id": case.rule_id,
        "state": case.state,
        "touches_used": case.touches_used,
        "spend_paise": case.intervention_cost_paise,
        "exception_reason": case.exception_reason,
        # The one piece of judgement the queue offers: is calling this case
        # capable of paying for itself at all?
        "below_break_even": (
            threshold is not None and case.amount_at_risk_paise < threshold
        ),
    }


def queue(db: Session, limit: int = 100,
          include_worked: bool = False) -> List[dict]:
    """
    Cases waiting on a person, most money first.

    Control-arm cases are excluded outright. They are classified and measured
    but never contacted, and putting one in front of an operator is how a
    control arm quietly stops being one.
    """
    threshold = break_even_paise()

    rows = [
        c for c in db.query(Case)
        .filter(Case.recovery_class == REVIEW_CLASS)
        .filter(Case.arm != "control")
        if include_worked or c.state not in WORKED_STATES
    ]
    rows.sort(key=lambda c: c.amount_at_risk_paise, reverse=True)
    return [_row(c, threshold) for c in rows[:limit]]


def economics(db: Session) -> dict:
    """
    What this lane costs, what it might return, and whether that is knowable.

    Reported together on purpose. The spend is a fact, the expected return is a
    projection from our assumptions, and the measurability is the reason the
    two cannot be reconciled from this batch alone.
    """
    cases = list(db.query(Case).filter(Case.recovery_class == REVIEW_CLASS))
    treatment = [c for c in cases if c.arm != "control"]
    control = [c for c in cases if c.arm == "control"]

    at_risk = sum(c.amount_at_risk_paise for c in treatment)
    spend = sum(c.intervention_cost_paise for c in treatment)
    lift = oracle.TIER_MARGINAL_LIFT.get((REVIEW_CLASS, HUMAN_TIER), 0.0)

    x_t = sum(1 for c in treatment if c.state == "RECOVERED")
    x_c = sum(1 for c in control if c.state == "RECOVERED")
    measured, lower, upper = lift_ci(x_t, len(treatment), x_c, len(control))
    p_c = (x_c / len(control)) if control else 0.0

    threshold = break_even_paise()
    below = [c for c in treatment
             if threshold is not None and c.amount_at_risk_paise < threshold]

    # Total spend across every lane, so the share is a fact rather than a
    # remembered figure.
    total_spend = sum(c.intervention_cost_paise for c in db.query(Case))

    return {
        "cases": len(treatment),
        "control_cases": len(control),
        "amount_at_risk_paise": at_risk,
        "spend_paise": spend,
        "share_of_total_spend": (spend / total_spend) if total_spend else 0.0,
        # What one review actually costs under the policy in force. Served
        # rather than written into the page, because it is a merchant's number
        # now - a page quoting Rs 50 would be confidently wrong for anyone who
        # changed it.
        "cost_per_review_paise": config.active().tier_cost_paise.get(
            HUMAN_TIER, 0),

        # What our assumptions imply. Labelled, because it is a projection.
        "assumed_marginal_lift": lift,
        "expected_incremental_paise": int(lift * at_risk),

        # What the batch could actually see.
        "measured_lift": measured,
        "ci_lower": lower,
        "ci_upper": upper,
        "is_significant": lower > 0,
        "required_n_per_arm": required_n_per_arm(p_c, lift) if lift else None,

        # Independent of sample size.
        "break_even_paise": threshold,
        "below_break_even": len(below),
        "below_break_even_paise": sum(c.amount_at_risk_paise for c in below),

        "reading": (
            "In expectation this lane looks worth it. It cannot be measured at "
            "this size, which is a different claim from losing money - and "
            "separately, the cases below break-even cannot pay back a call "
            "however large the sample gets."
        ),
    }
