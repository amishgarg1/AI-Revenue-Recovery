"""
Measurement.

The number nearly every recovery demo reports is gross recovery: "we recovered
₹4.2 lakh." It is the wrong number, because some of those customers would have
come back on their own. Gross recovery measures the agent plus the world; only
the difference against an untouched control arm measures the agent.

So RecoverOS holds out 20% of cases, never contacts them, and reports the
difference — with a confidence interval, and with an explicit verdict when the
sample is too small to call. A lift we cannot distinguish from zero is
reported as exactly that.
"""

import math
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

Z_95 = 1.96


def lift_ci(x_t: int, n_t: int, x_c: int, n_c: int,
            z: float = Z_95) -> Tuple[float, float, float]:
    """
    Two-proportion difference with a normal-approximation confidence interval.

    Returns (lift, lower, upper) as proportions. The interval is what makes the
    point estimate honest: an 8-point lift with an interval spanning zero is
    not an 8-point lift, it is "we cannot tell yet".
    """
    if n_t == 0 or n_c == 0:
        return 0.0, 0.0, 0.0

    p_t, p_c = x_t / n_t, x_c / n_c
    se = math.sqrt(p_t * (1 - p_t) / n_t + p_c * (1 - p_c) / n_c)
    d = p_t - p_c
    return d, d - z * se, d + z * se


def required_n_per_arm(p_c: float, mde: float, alpha_z: float = Z_95,
                       power_z: float = 0.84) -> int:
    """
    Sample size per arm needed to detect `mde` at 95% confidence and 80% power.

    Reported alongside a null result so "not significant" comes with "here is
    what it would take", rather than being left as a shrug.
    """
    p_t = min(max(p_c + mde, 0.0001), 0.9999)
    p_bar = (p_c + p_t) / 2
    numerator = (alpha_z * math.sqrt(2 * p_bar * (1 - p_bar))
                 + power_z * math.sqrt(p_c * (1 - p_c) + p_t * (1 - p_t))) ** 2
    return int(math.ceil(numerator / (mde ** 2))) if mde else 0


def _recovered(case: dict) -> bool:
    return case.get("state") == "RECOVERED"


def calculate_experiment_results(cases: List[dict],
                                 guardrails: Optional[dict] = None) -> Dict:
    """
    Full experiment readout from the case table.

    `cases` are plain dicts so this stays testable without a database.
    """
    arms = {"treatment": [], "control": []}
    for c in cases:
        arm = c.get("arm")
        if arm in arms:
            arms[arm].append(c)

    treat, ctrl = arms["treatment"], arms["control"]
    n_t, n_c = len(treat), len(ctrl)
    x_t = sum(1 for c in treat if _recovered(c))
    x_c = sum(1 for c in ctrl if _recovered(c))

    lift, lo, hi = lift_ci(x_t, n_t, x_c, n_c)

    at_risk_t = sum(c.get("amount_at_risk_paise", 0) for c in treat)
    at_risk_c = sum(c.get("amount_at_risk_paise", 0) for c in ctrl)
    gross_recovered_t = sum(c.get("recovered_paise", 0) for c in treat)
    gross_recovered_c = sum(c.get("recovered_paise", 0) for c in ctrl)
    spend = sum(c.get("intervention_cost_paise", 0) for c in treat)

    avg_ticket_t = at_risk_t / n_t if n_t else 0
    incremental_cases = lift * n_t
    incremental_paise = incremental_cases * avg_ticket_t
    incremental_lo = lo * n_t * avg_ticket_t
    incremental_hi = hi * n_t * avg_ticket_t

    significant = lo > 0
    p_c = x_c / n_c if n_c else 0.0
    needed = required_n_per_arm(p_c, max(lift, 0.01)) if not significant else None

    # Case-count lift treats a Rs 200 cart and a Rs 90,000 invoice as equal. The
    # value-weighted version answers the question a merchant actually asks: what
    # fraction of the money at risk came back? It is the more conservative of
    # the two here, so it is what the headline rupee figure uses.
    value_rate_t = gross_recovered_t / at_risk_t if at_risk_t else 0.0
    value_rate_c = gross_recovered_c / at_risk_c if at_risk_c else 0.0
    value_lift = value_rate_t - value_rate_c
    value_incremental_paise = value_lift * at_risk_t

    # How large the lift would have had to be for the campaign to merely pay for
    # its own messaging. If this number is tiny next to the observed lift, the
    # economics are not close.
    breakeven_lift = (spend / at_risk_t) if at_risk_t else 0.0

    return {
        "treatment_n": n_t,
        "treatment_recovered": x_t,
        "treatment_rate": x_t / n_t if n_t else 0.0,
        "control_n": n_c,
        "control_recovered": x_c,
        "control_rate": p_c,

        "net_lift": lift,
        "ci_lower": lo,
        "ci_upper": hi,
        "is_significant": significant,
        "required_n_per_arm": needed,

        "amount_at_risk_paise": at_risk_t + at_risk_c,
        "treatment_at_risk_paise": at_risk_t,
        "control_at_risk_paise": at_risk_c,
        "gross_recovered_paise": gross_recovered_t + gross_recovered_c,
        "treatment_gross_recovered_paise": gross_recovered_t,
        "control_gross_recovered_paise": gross_recovered_c,

        # The headline. Gross recovery minus what the control arm says would
        # have happened anyway.
        "incremental_recovered_paise": incremental_paise,
        "incremental_ci_lower_paise": incremental_lo,
        "incremental_ci_upper_paise": incremental_hi,
        "incremental_cases": incremental_cases,

        "value_recovery_rate_treatment": value_rate_t,
        "value_recovery_rate_control": value_rate_c,
        "value_weighted_lift": value_lift,
        "value_incremental_paise": value_incremental_paise,
        "breakeven_lift": breakeven_lift,

        "intervention_cost_paise": spend,
        # Variable messaging cost only. It does not include the platform, the
        # engineering, or the support load a real deployment would carry, so it
        # is an upper bound on ROI and is labelled that way everywhere it appears.
        "roi": (value_incremental_paise / spend) if spend else 0.0,
        "roi_basis": "variable messaging cost only",
        "cost_per_incremental_recovery_paise": (
            spend / incremental_cases if incremental_cases > 0.5 else None
        ),
        "guardrails": guardrails or {},
    }


def per_class_breakdown(cases: List[dict]) -> List[dict]:
    """
    The same treatment-vs-control comparison, split by recovery class.

    Aggregate lift can hide a class that is being actively harmed by outreach.
    Splitting it out is how you find that out before a merchant does.
    """
    buckets = defaultdict(lambda: {"t": [], "c": []})
    for c in cases:
        rc = c.get("recovery_class") or "UNCLASSIFIED"
        if c.get("arm") == "treatment":
            buckets[rc]["t"].append(c)
        elif c.get("arm") == "control":
            buckets[rc]["c"].append(c)

    rows = []
    for rc, group in buckets.items():
        n_t, n_c = len(group["t"]), len(group["c"])
        x_t = sum(1 for c in group["t"] if _recovered(c))
        x_c = sum(1 for c in group["c"] if _recovered(c))
        lift, lo, hi = lift_ci(x_t, n_t, x_c, n_c)
        rows.append({
            "recovery_class": rc,
            "treatment_n": n_t,
            "treatment_rate": x_t / n_t if n_t else 0.0,
            "control_n": n_c,
            "control_rate": x_c / n_c if n_c else 0.0,
            "net_lift": lift,
            "ci_lower": lo,
            "ci_upper": hi,
            "is_significant": lo > 0,
            "spend_paise": sum(c.get("intervention_cost_paise", 0) for c in group["t"]),
            "at_risk_paise": sum(
                c.get("amount_at_risk_paise", 0) for c in group["t"] + group["c"]
            ),
        })
    rows.sort(key=lambda r: r["at_risk_paise"], reverse=True)
    return rows


def exception_report(cases: List[dict]) -> List[dict]:
    """
    Everything that was not recovered, grouped by why.

    This is deliberately part of the primary output rather than an appendix. A
    recovery system that only reports its wins is not reporting.
    """
    groups = defaultdict(lambda: {"count": 0, "amount_paise": 0, "classes": defaultdict(int)})
    for c in cases:
        if _recovered(c):
            continue
        reason = c.get("exception_reason") or "Unresolved - no reason recorded"
        g = groups[reason]
        g["count"] += 1
        g["amount_paise"] += c.get("amount_at_risk_paise", 0)
        g["classes"][c.get("recovery_class") or "UNCLASSIFIED"] += 1

    rows = [
        {
            "reason": reason,
            "count": g["count"],
            "amount_paise": g["amount_paise"],
            "by_class": dict(g["classes"]),
        }
        for reason, g in groups.items()
    ]
    rows.sort(key=lambda r: r["amount_paise"], reverse=True)
    return rows
