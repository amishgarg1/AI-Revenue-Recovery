"""
How wrong can the assumptions be before the conclusion changes?

`docs/assumptions.md` lists seventy-three numbers we chose rather than
measured, and the headline result rests on them. Reporting "+14.4 points" as
though it were an observation is the single most misleading thing this project
could do: what we actually have is *"+14.4 points, if the base rates we picked
are right."*

So this module does the obvious next thing. It moves each assumption through a
range of plausible values and reports what happens to the answer. Two questions
matter:

**Which assumption is the result most exposed to?** The tornado ranking. An
assumption that swings the lift by a tenth of a point is not worth arguing
about; one that swings it by six points is the number a reviewer should attack
first.

**How wrong would we have to be to be wrong?** The breaking point. It is more
useful to say "this conclusion survives every base rate up to sixty percent
above ours" than to defend the specific value we chose.

Why this is cheap
-----------------
The agent never reads the oracle - `app/core/*` does not import it. So the
decisions are *invariant* to these parameters: perturbing a base rate cannot
change which messages were sent, only whether the customer paid. That means a
sensitivity run is a recomputation over the recorded actions, not eighty
re-runs of the batch. The architectural rule that keeps the experiment honest
is the same one that makes this affordable.

What this cannot tell you
-------------------------
It varies our assumptions within our model. If the *shape* of the model is
wrong - if lift is not additive across touches, or if contacting someone twice
annoys them into not paying - no amount of moving these numbers will reveal it.
That is a limitation of simulation, not of the analysis, and the only cure is
real outcome data.
"""

from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from app.analytics.experiment import lift_ci
from app.models import Action, Case
from app.sim import oracle

# Each assumption is moved across this range, as a multiplier on its committed
# value. Wide on purpose: a plausible-looking +/-10% band would flatter us, and
# the interesting question is where the answer breaks rather than whether it
# wobbles.
SWEEP = (0.4, 0.6, 0.8, 1.0, 1.2, 1.4, 1.6, 2.0)

# Bands used to describe a swing in words. A reader should not have to hold the
# headline lift in their head to know whether 0.4pp matters.
NEGLIGIBLE_PP = 0.5
MODERATE_PP = 2.0


def observed_run(db: Session) -> List[dict]:
    """
    The recorded run, reduced to what an outcome depends on.

    One row per case: its class, its arm, and the tiers actually delivered to
    it. Everything else about the run - which gate refused what, when a message
    went out - is irrelevant here, because the oracle only ever saw these three
    things.
    """
    delivered: Dict[str, List[int]] = {}
    for action in db.query(Action).filter(Action.status == "SENT"):
        delivered.setdefault(action.case_id, []).append(action.tier)

    return [
        {
            "case_id": c.case_id,
            "recovery_class": c.recovery_class,
            "arm": c.arm,
            # A control case is never contacted, so its tier list is empty by
            # definition rather than by observation.
            "tiers": tuple(sorted(delivered.get(c.case_id, [])))
            if c.arm != "control" else (),
        }
        for c in db.query(Case)
        if c.recovery_class
    ]


def _recovered(row: dict, baseline: Dict[str, float],
               marginal: Dict[tuple, float], ceiling: float) -> bool:
    """
    Re-decide one case under a different set of assumptions.

    Deliberately mirrors `oracle.determine_outcome` rather than calling it, so
    the parameters can be substituted without mutating module state - a
    sensitivity sweep that leaves the oracle changed would poison every later
    query in the same process.
    """
    p = baseline.get(row["recovery_class"], 0.0)
    for tier in row["tiers"]:
        p += marginal.get((row["recovery_class"], tier), 0.0)
    return oracle.recovery_draw(row["case_id"]) < min(p, ceiling)


def evaluate(rows: List[dict], baseline: Dict[str, float],
             marginal: Dict[tuple, float], ceiling: float) -> dict:
    """Net lift and its interval under one set of assumptions."""
    n_t = x_t = n_c = x_c = 0
    for row in rows:
        recovered = _recovered(row, baseline, marginal, ceiling)
        if row["arm"] == "control":
            n_c += 1
            x_c += recovered
        else:
            n_t += 1
            x_t += recovered

    lift, lower, upper = lift_ci(x_t, n_t, x_c, n_c)
    return {
        "treatment_rate": x_t / n_t if n_t else 0.0,
        "control_rate": x_c / n_c if n_c else 0.0,
        "net_lift": lift,
        "ci_lower": lower,
        "ci_upper": upper,
        # The conclusion, not the number. This is what the sweep is testing.
        "is_significant": lower > 0,
    }


def _scaled(mapping, factor: float, only_key=None):
    """A copy with one key - or every key - multiplied by `factor`."""
    return {
        k: (v * factor if only_key is None or k == only_key else v)
        for k, v in mapping.items()
    }


def _describe(swing_pp: float) -> str:
    if swing_pp < NEGLIGIBLE_PP:
        return "negligible"
    if swing_pp < MODERATE_PP:
        return "moderate"
    return "material"


def sweep_parameter(rows: List[dict], label: str, kind: str,
                    key=None) -> dict:
    """
    Move one assumption across SWEEP and record what the lift does.

    `kind` says what is being scaled: every baseline at once, one class's
    baseline, every marginal lift, one rung's lift, or the ceiling.
    """
    points = []
    for factor in SWEEP:
        baseline = oracle.NO_INTERVENTION_BASELINE
        marginal = oracle.TIER_MARGINAL_LIFT
        ceiling = oracle.MAX_RECOVERY_PROBABILITY

        if kind == "baseline_all":
            baseline = _scaled(baseline, factor)
        elif kind == "baseline_one":
            baseline = _scaled(baseline, factor, key)
        elif kind == "marginal_all":
            marginal = _scaled(marginal, factor)
        elif kind == "marginal_one":
            marginal = _scaled(marginal, factor, key)
        elif kind == "ceiling":
            ceiling = min(ceiling * factor, 1.0)

        result = evaluate(rows, baseline, marginal, ceiling)
        points.append({"factor": factor, **result})

    lifts = [p["net_lift"] for p in points]
    swing_pp = (max(lifts) - min(lifts)) * 100

    # Where the conclusion - significance, not the point estimate - stops
    # holding. None means it held across the entire sweep.
    breaks_at = next(
        (p["factor"] for p in points if not p["is_significant"]), None
    )

    return {
        "label": label,
        "kind": kind,
        "key": str(key) if key is not None else None,
        "points": points,
        "low_lift": min(lifts),
        "high_lift": max(lifts),
        "swing_pp": swing_pp,
        "impact": _describe(swing_pp),
        "breaks_at": breaks_at,
    }


def _significant_at(rows: List[dict], kind: str, key, factor: float) -> bool:
    baseline = oracle.NO_INTERVENTION_BASELINE
    marginal = oracle.TIER_MARGINAL_LIFT
    ceiling = oracle.MAX_RECOVERY_PROBABILITY

    if kind == "baseline_all":
        baseline = _scaled(baseline, factor)
    elif kind == "baseline_one":
        baseline = _scaled(baseline, factor, key)
    elif kind == "marginal_all":
        marginal = _scaled(marginal, factor)
    elif kind == "marginal_one":
        marginal = _scaled(marginal, factor, key)
    elif kind == "ceiling":
        ceiling = min(ceiling * factor, 1.0)

    return evaluate(rows, baseline, marginal, ceiling)["is_significant"]


def breaking_point(rows: List[dict], sweep: dict, tolerance: float = 0.005) -> Optional[float]:
    """
    The exact factor at which this assumption stops carrying the conclusion.

    The sweep only tells you it broke somewhere between two coarse steps.
    "Holds until interventions are half as effective as we assumed" is a
    sentence you can defend; "holds at 0.6 and fails at 0.4" is not, because
    nobody's real base rates land on our grid.

    Bisects between the last factor that held and the first that did not.
    Returns None when nothing in the tested range breaks it.

    Outcomes are a step function of the factor - a case flips only when the
    probability crosses its fixed draw - so significance is not guaranteed to
    be monotonic. In practice it is, because thousands of cases move together;
    bisection assumes that, and the returned figure is quoted to two decimals
    rather than presented as exact.
    """
    if sweep["breaks_at"] is None:
        return None

    kind, key = sweep["kind"], sweep["key"]
    if kind in ("baseline_one", "marginal_one"):
        # `key` was stringified for transport; recover the original.
        key = next(
            k for k in (oracle.NO_INTERVENTION_BASELINE if kind == "baseline_one"
                        else oracle.TIER_MARGINAL_LIFT)
            if str(k) == key
        )

    # Bracket between the highest factor that failed and the lowest above it
    # that held, taken from the sweep we already ran rather than re-derived.
    # Bracketing against the far end of the range instead would only work while
    # significance stays monotonic across the whole sweep.
    failed = [p["factor"] for p in sweep["points"] if not p["is_significant"]]
    held_above = [p["factor"] for p in sweep["points"]
                  if p["is_significant"] and p["factor"] > max(failed)]
    if not held_above:
        return max(failed)

    broken, held = max(failed), min(held_above)

    while held - broken > tolerance:
        mid = (held + broken) / 2
        if _significant_at(rows, kind, key, mid):
            held = mid
        else:
            broken = mid

    return round(held, 3)


def run_fingerprint(db: Session) -> tuple:
    """
    Cheap identity for the recorded run.

    Three counts that all move when a batch is re-run and none of which move
    otherwise. Used as the cache key below, in preference to a timestamp: a
    clock would expire a still-valid answer and, worse, keep serving a stale
    one for the rest of its window after a fresh batch.
    """
    from sqlalchemy import func

    return (
        db.query(func.count(Case.case_id)).scalar(),
        db.query(func.count(Action.action_id))
          .filter(Action.status == "SENT").scalar(),
        db.query(func.max(Action.action_id)).scalar(),
    )


# The full sweep is around thirty parameters times eight factors plus a
# bisection, over every case - six seconds on the committed run. That is fine
# once and unacceptable on every dashboard load, and the inputs cannot change
# without the fingerprint changing.
_cache: dict = {}


def clear_cache():
    """Drop the memo. Tests that rebuild a database in place need this."""
    _cache.clear()


def sensitivity_report(db: Session, rows: Optional[List[dict]] = None) -> dict:
    """
    The full sweep, ranked by how much each assumption moves the answer.

    Ordered so the first row is the one a reviewer should attack first.
    Memoised against the run it describes; pass `rows` to bypass the cache.
    """
    if rows is None:
        key = run_fingerprint(db)
        if key in _cache:
            return _cache[key]
        report = _compute(observed_run(db))
        # Only ever one run in flight, so the memo does not need to grow.
        _cache.clear()
        _cache[key] = report
        return report

    return _compute(rows)


def _compute(rows: List[dict]) -> dict:
    committed = evaluate(
        rows,
        oracle.NO_INTERVENTION_BASELINE,
        oracle.TIER_MARGINAL_LIFT,
        oracle.MAX_RECOVERY_PROBABILITY,
    )

    sweeps = [
        sweep_parameter(rows, "Every no-intervention baseline", "baseline_all"),
        sweep_parameter(rows, "Every marginal lift per rung", "marginal_all"),
        sweep_parameter(rows, "Recovery probability ceiling", "ceiling"),
    ]

    # Then each class's own baseline, and each rung's own lift. A class that
    # carries few cases cannot move the aggregate however wrong it is, and
    # showing that is part of the point.
    for cls in sorted(oracle.NO_INTERVENTION_BASELINE):
        sweeps.append(sweep_parameter(
            rows, f"{cls} baseline", "baseline_one", key=cls))

    for key in sorted(oracle.TIER_MARGINAL_LIFT):
        cls, tier = key
        sweeps.append(sweep_parameter(
            rows, f"{cls} tier {tier} lift", "marginal_one", key=key))

    sweeps.sort(key=lambda s: s["swing_pp"], reverse=True)

    # The headline finding: the smallest perturbation anywhere that flips
    # significance. If nothing flips, the conclusion held across every
    # assumption at every factor tested, which is the strongest thing the
    # analysis can say.
    breakers = []
    for s in sweeps:
        if s["breaks_at"] is None:
            continue
        exact = breaking_point(rows, s)
        s["breaking_point"] = exact
        breakers.append({
            "label": s["label"],
            "breaks_at": s["breaks_at"],
            "breaking_point": exact,
            # The same figure said the way a reader would say it.
            "wrong_by_pct": round((1 - exact) * 100) if exact and exact < 1
                            else round((exact - 1) * 100) if exact else None,
        })

    return {
        "committed": committed,
        "sweep_factors": list(SWEEP),
        "parameters": sweeps,
        "material_count": sum(1 for s in sweeps if s["impact"] == "material"),
        "breakers": breakers,
        "conclusion_holds": not breakers,
    }
