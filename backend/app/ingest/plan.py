"""
What the policy would do to a real backlog.

Given somebody's failed payments, this reports the plan: how each one is
classified, what would be sent, what would be refused and by which gate, and
what it would cost. Same classifier, same ladder, same eleven gates the batch
uses - imported, not reimplemented.

The honest limit, stated once here and repeated in the output
---------------------------------------------------------------
On a merchant's own data we know what we would *do*. We do not know what they
would *recover*, because nobody ran the experiment on their customers. Any
recovery figure here is our base rates applied to their volumes, which is a
projection and not a measurement.

So it is reported as a range rather than a number, and the range is the one
`app/analytics/sensitivity.py` establishes: the assumptions swept across the
band where the published conclusion still holds. A single confident figure on
somebody else's data would be the most dishonest thing this project could
print.

Why the plan picks its own hour
-------------------------------
The gates read the clock, so uploading at midnight would refuse almost
everything on quiet hours and tell the merchant nothing about their backlog.
The plan is evaluated inside the merchant's *own* contact window, so what it
shows is what is structurally refused: no consent, below the viability floor,
risk-blocked, already paid. Timing refusals are a scheduling question, and the
batch answers those.

It has to be the merchant's window rather than a fixed hour. A first version
used 11:00 IST, which is inside every window under the default policy and
inside the quiet hours of a merchant in another timezone - so their plan came
back refusing everything on G02, which is exactly the useless answer this is
meant to avoid.
"""

from collections import Counter, defaultdict
from typing import List, Optional

from app.core import config
from app.core.classifier import classify
from app.core.clock import IST, datetime
from app.core.ladder import get_next_action
from app.core.policy import evaluate
from app.sim import oracle

# The default policy's window, used when a merchant's own cannot be resolved.
PLAN_HOUR_IST = 11


def planning_hour(policy) -> int:
    """
    An hour inside this merchant's contact window.

    The midpoint of the voice window, which is the narrowest of the two and is
    validated to run forwards, so it always sits inside the wider messaging
    window too. Falls back to scanning the day if a policy somehow has no
    contactable hour - which the config validator should already have refused.
    """
    from app.core.policy import _in_quiet_window

    midpoint = (policy.voice_start_ist + policy.voice_end_ist) // 2
    if not _in_quiet_window(midpoint, policy):
        return midpoint

    for hour in range(24):
        if not _in_quiet_window(hour, policy):
            return hour
    return PLAN_HOUR_IST


def _planning_moment(policy) -> datetime:
    """A stated hour inside the merchant's window. See the module docstring."""
    return datetime(2026, 1, 1, planning_hour(policy), 0, tzinfo=IST)


def _projection(class_counts: Counter, plan_rows: List[dict]) -> dict:
    """
    What our base rates would predict, and how wide that is.

    Two figures, both labelled: the incremental recovery our assumptions imply,
    and the band it moves through when those assumptions are swept across the
    range where the published conclusion still holds. The band is the honest
    part - it is roughly a factor of two, and a merchant should see that before
    they see a number.
    """
    # The sweep found the published result survives down to x0.759 of the
    # assumed marginal lifts. Anything outside that band is a range in which we
    # have already said we could not tell.
    LOW, HIGH = 0.759, 1.4

    def incremental(scale: float) -> int:
        total = 0
        for row in plan_rows:
            if not row["would_send"]:
                continue
            lift = sum(
                oracle.TIER_MARGINAL_LIFT.get((row["recovery_class"], t), 0.0)
                for t in row["tiers_planned"]
            ) * scale
            total += lift * row["amount_at_risk_paise"]
        return int(total)

    return {
        "at_our_assumptions_paise": incremental(1.0),
        "low_paise": incremental(LOW),
        "high_paise": incremental(HIGH),
        "band": [LOW, HIGH],
        "basis": (
            "Our base rates applied to your volumes. Nobody ran this "
            "experiment on your customers, so this is a projection, not a "
            "measurement. The band is the range over which our published "
            "conclusion still holds - see docs/sensitivity.md."
        ),
    }


def build_plan(rows: List[dict], merchant_id: Optional[str] = None) -> dict:
    """
    Classify every row, pick its next rung, and run the gates.

    Returns counts and money only. No row from the input appears in the
    output, because the input is somebody's customer data.
    """
    policy = config.active(merchant_id)
    now = _planning_moment(policy)
    plan_hour = planning_hour(policy)

    class_counts: Counter = Counter()
    rule_counts: Counter = Counter()
    channel_counts: Counter = Counter()
    refusals: dict = defaultdict(lambda: {"blocks": 0, "reasons": Counter(),
                                          "amount_paise": 0})

    plan_rows: List[dict] = []
    total_at_risk = 0
    planned_spend = 0
    would_send = 0
    no_action = 0

    for row in rows:
        total_at_risk += row["amount_at_risk_paise"]

        case = {
            "entity_type": row["entity_type"],
            "entity_id": row["entity_id"],
            "entity_status": row["entity_status"],
            "amount_at_risk_paise": row["amount_at_risk_paise"],
            "days_overdue": row["days_overdue"],
            "state": "OPEN",
            "touches_used": 0,
            "promise_date": None,
        }

        classification = classify(case, [row["payment"]])
        recovery_class = classification.recovery_class.value
        class_counts[recovery_class] += 1
        rule_counts[classification.rule_id] += 1

        intent = get_next_action(recovery_class, touches_used=0,
                                 amount_paise=row["amount_at_risk_paise"])
        if intent is None:
            no_action += 1
            plan_rows.append({
                "recovery_class": recovery_class,
                "would_send": False,
                "tiers_planned": (),
                "amount_at_risk_paise": row["amount_at_risk_paise"],
            })
            continue

        decision = evaluate(case, intent, {
            "now": now,
            "tick": None,
            # An export carries no consent record; that lives in the merchant's
            # own customer table. Consent is assumed present so the plan shows
            # what the *other* gates would do - and the output says so, because
            # assuming consent silently would overstate what can be sent.
            "customer": {"consent_whatsapp": True, "consent_sms": True,
                         "consent_email": True, "consent_voice": False,
                         "dnd_registered": False, "opted_out": False},
            "entity_status": row["entity_status"],
            "issuer": row["payment"]["issuer"],
            "customer_touches_24h": 0,
            "customer_touches_7d": 0,
            "last_tier": None,
            "policy": policy,
        })

        if decision.allowed:
            would_send += 1
            planned_spend += intent.cost_paise
            channel_counts[intent.channel] += 1
            plan_rows.append({
                "recovery_class": recovery_class,
                "would_send": True,
                "tiers_planned": (intent.tier,),
                "amount_at_risk_paise": row["amount_at_risk_paise"],
            })
        else:
            entry = refusals[decision.blocked_by]
            entry["blocks"] += 1
            entry["reasons"][decision.reason_code] += 1
            entry["amount_paise"] += row["amount_at_risk_paise"]
            plan_rows.append({
                "recovery_class": recovery_class,
                "would_send": False,
                "tiers_planned": (),
                "amount_at_risk_paise": row["amount_at_risk_paise"],
            })

    return {
        "cases": len(rows),
        "amount_at_risk_paise": total_at_risk,
        "would_contact": would_send,
        "would_not_contact": len(rows) - would_send,
        "no_action_possible": no_action,
        "planned_spend_paise": planned_spend,
        "by_class": [
            {"recovery_class": k, "cases": v}
            for k, v in class_counts.most_common()
        ],
        "by_rule": [
            {"rule_id": k, "cases": v} for k, v in rule_counts.most_common()
        ],
        "by_channel": [
            {"channel": k, "messages": v} for k, v in channel_counts.most_common()
        ],
        "refusals": [
            {
                "gate": gate,
                "blocks": entry["blocks"],
                "amount_paise": entry["amount_paise"],
                "reasons": dict(entry["reasons"]),
            }
            for gate, entry in sorted(
                refusals.items(), key=lambda kv: kv[1]["blocks"], reverse=True)
        ],
        "projection": _projection(class_counts, plan_rows),
        "policy": policy.label,
        "evaluated_at_ist_hour": plan_hour,
        "assumptions": [
            "Consent is assumed present for messaging channels - your export "
            "does not carry consent state, and G01 would refuse anyone who has "
            "opted out or is on the DND registry.",
            f"Evaluated at {plan_hour}:00 IST, inside this policy's own "
            "contact window, so refusals here are structural rather than "
            "timing.",
            "First touch only. The full ladder escalates over seven days; this "
            "is what would happen on day one.",
        ],
    }
