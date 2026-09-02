"""
Time-series and flow endpoints.

The batch is a seven-day simulation, and until now none of that was visible
anywhere: the dashboard showed totals, which is what every recovery dashboard
shows. The interesting shape is *when* things happened — the dead bands where
quiet hours suppress everything, the issuer outage holding retries at the start,
and the slow divergence between the treated arm and the untouched one.

That divergence is the product. It deserves to be the thing on screen.
"""

from collections import defaultdict
from typing import Dict, List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core import clock
from app.core.detector import detector
from app.db import get_db
from app.models import Action, Case, Payment

router = APIRouter(prefix="/api", tags=["timeline"])


@router.get("/metrics/timeline")
def timeline(db: Session = Depends(get_db)) -> Dict:
    """
    Per-tick activity and the cumulative recovery curve for each arm.

    Recoveries are attributed to the tick they resolved on, so the two
    cumulative series can be plotted against each other. The gap between them
    at the final tick is the incremental lift — the same number the experiment
    page reports, drawn rather than stated.
    """
    ticks = clock.TICK_COUNT

    sent = [0] * ticks
    blocked = [0] * ticks
    spend = [0] * ticks
    by_gate: List[Dict[str, int]] = [defaultdict(int) for _ in range(ticks)]
    by_tier: List[Dict[str, int]] = [defaultdict(int) for _ in range(ticks)]

    for a in db.query(Action):
        # Seeded legacy outreach sits at tick -1: it is history the frequency
        # cap has to respect, not something this run did.
        if a.tick is None or a.tick < 0 or a.tick >= ticks:
            continue
        if a.status == "SENT":
            sent[a.tick] += 1
            spend[a.tick] += a.cost_paise or 0
            by_tier[a.tick][str(a.tier)] += 1
        else:
            blocked[a.tick] += 1
            if a.blocked_by:
                by_gate[a.tick][a.blocked_by] += 1

    recovered = {"treatment": [0] * ticks, "control": [0] * ticks}
    recovered_paise = {"treatment": [0] * ticks, "control": [0] * ticks}
    arm_totals = {"treatment": 0, "control": 0}

    for case in db.query(Case):
        arm = case.arm
        if arm not in arm_totals:
            continue
        arm_totals[arm] += 1
        if case.state != "RECOVERED":
            continue
        t = case.resolved_tick
        if t is None:
            continue
        t = min(max(t, 0), ticks - 1)
        recovered[arm][t] += 1
        recovered_paise[arm][t] += case.recovered_paise or 0

    def cumulative(series):
        out, running = [], 0
        for v in series:
            running += v
            out.append(running)
        return out

    cum = {arm: cumulative(recovered[arm]) for arm in recovered}
    cum_paise = {arm: cumulative(recovered_paise[arm]) for arm in recovered_paise}
    cum_spend = cumulative(spend)

    # The outage window, expressed in ticks, so the chart can shade the period
    # when retries were being held rather than spent.
    if not detector.health_report():
        detector.load_payments(
            [{c.name: getattr(p, c.name) for c in p.__table__.columns}
             for p in db.query(Payment)]
        )
    outages = []
    for report in detector.health_report():
        if not report["spike_windows"]:
            continue
        until = detector.degraded_until(report["issuer"])
        if until is None:
            continue
        end_tick = (until - clock.BATCH_START).total_seconds() / 3600 / clock.TICK_HOURS
        if end_tick > 0:
            outages.append({
                "issuer": report["issuer"],
                "start_tick": 0,          # already degraded when the batch began
                "end_tick": round(end_tick, 2),
                "peak_failures": report["peak_failures_in_window"],
            })

    rows = []
    for i in range(ticks):
        at = clock.BATCH_START + clock.timedelta(hours=i * clock.TICK_HOURS)
        hour = clock.ist_hour(at)
        rows.append({
            "tick": i,
            "at": clock.iso(at),
            "ist_hour": hour,
            "day": (at - clock.BATCH_START).days,
            # Shaded on the chart. Seeing the nightly dead bands is what makes
            # the quiet-hours rule believable.
            "quiet": hour >= 21 or hour < 9,
            "sent": sent[i],
            "blocked": blocked[i],
            "spend_paise": spend[i],
            "cum_spend_paise": cum_spend[i],
            "recovered_treatment": recovered["treatment"][i],
            "recovered_control": recovered["control"][i],
            "cum_treatment": cum["treatment"][i],
            "cum_control": cum["control"][i],
            "cum_treatment_paise": cum_paise["treatment"][i],
            "cum_control_paise": cum_paise["control"][i],
            "by_gate": dict(by_gate[i]),
            "by_tier": dict(by_tier[i]),
        })

    return {
        "ticks": ticks,
        "tick_hours": clock.TICK_HOURS,
        "batch_start": clock.iso(clock.BATCH_START),
        "arm_totals": arm_totals,
        "outages": outages,
        "rows": rows,
    }


@router.get("/metrics/flow")
def flow(db: Session = Depends(get_db)) -> Dict:
    """
    Where every rupee at risk ended up.

    Structured as stages so the front end can draw it as a flow rather than a
    stack of unrelated totals: at risk → routed by class → treated or held out
    → recovered or not.
    """
    cases = list(db.query(Case))
    total = sum(c.amount_at_risk_paise or 0 for c in cases)

    by_class = defaultdict(lambda: {
        "at_risk_paise": 0, "recovered_paise": 0, "cases": 0,
        "recovered_cases": 0, "spend_paise": 0,
    })
    by_arm = defaultdict(lambda: {
        "at_risk_paise": 0, "recovered_paise": 0, "cases": 0, "recovered_cases": 0,
    })

    for c in cases:
        cls = by_class[c.recovery_class or "UNCLASSIFIED"]
        cls["at_risk_paise"] += c.amount_at_risk_paise or 0
        cls["recovered_paise"] += c.recovered_paise or 0
        cls["spend_paise"] += c.intervention_cost_paise or 0
        cls["cases"] += 1

        arm = by_arm[c.arm or "unknown"]
        arm["at_risk_paise"] += c.amount_at_risk_paise or 0
        arm["recovered_paise"] += c.recovered_paise or 0
        arm["cases"] += 1

        if c.state == "RECOVERED":
            cls["recovered_cases"] += 1
            arm["recovered_cases"] += 1

    classes = [
        {"recovery_class": name, **values}
        for name, values in sorted(
            by_class.items(), key=lambda kv: -kv[1]["at_risk_paise"]
        )
    ]

    return {
        "at_risk_paise": total,
        "recovered_paise": sum(c.recovered_paise or 0 for c in cases),
        "spend_paise": sum(c.intervention_cost_paise or 0 for c in cases),
        "by_class": classes,
        "by_arm": {k: v for k, v in by_arm.items()},
    }
