"""
Experiment tests.

The measurement is the claim, so these check the arithmetic *and* the honesty:
a lift whose interval crosses zero must be reported as not significant.
"""

import pytest

from app.analytics.experiment import (
    calculate_experiment_results, exception_report, lift_ci,
    per_class_breakdown, required_n_per_arm,
)
from app.sim.generator import assign_arm, assign_arms


def case(arm, recovered, amount=100_000, cost=0, rc="NUDGE_CUSTOMER",
         reason=None, case_id="c") -> dict:
    return {
        "case_id": case_id,
        "arm": arm,
        "state": "RECOVERED" if recovered else "EXHAUSTED",
        "recovery_class": rc,
        "amount_at_risk_paise": amount,
        "recovered_paise": amount if recovered else 0,
        "intervention_cost_paise": cost,
        "exception_reason": reason,
    }


def cohort(n_t, x_t, n_c, x_c, **kw):
    return (
        [case("treatment", i < x_t, case_id=f"t{i}", **kw) for i in range(n_t)]
        + [case("control", i < x_c, case_id=f"c{i}", **kw) for i in range(n_c)]
    )


# ------------------------------------------------------------------ lift maths

def test_lift_is_the_difference_of_two_rates():
    lift, lo, hi = lift_ci(40, 100, 20, 100)
    assert lift == pytest.approx(0.20)
    assert lo < lift < hi


def test_identical_arms_produce_no_lift():
    lift, lo, hi = lift_ci(20, 100, 20, 100)
    assert lift == pytest.approx(0.0)
    assert lo < 0 < hi


def test_a_bigger_sample_narrows_the_interval():
    _, small_lo, small_hi = lift_ci(40, 100, 20, 100)
    _, big_lo, big_hi = lift_ci(400, 1000, 200, 1000)
    assert (big_hi - big_lo) < (small_hi - small_lo)


def test_empty_arms_do_not_explode():
    assert lift_ci(0, 0, 0, 0) == (0.0, 0.0, 0.0)


# ------------------------------------------------------------------ honesty

def test_an_interval_crossing_zero_is_reported_as_not_significant():
    result = calculate_experiment_results(cohort(50, 12, 50, 10))
    assert result["net_lift"] > 0
    assert result["ci_lower"] < 0
    assert not result["is_significant"]
    # And it must say what it would take, rather than leaving a shrug.
    assert result["required_n_per_arm"] > 50


def test_a_clear_effect_is_reported_as_significant():
    result = calculate_experiment_results(cohort(400, 200, 400, 80))
    assert result["is_significant"]
    assert result["ci_lower"] > 0
    assert result["required_n_per_arm"] is None


def test_required_sample_size_grows_as_the_effect_shrinks():
    assert required_n_per_arm(0.20, 0.02) > required_n_per_arm(0.20, 0.10)


# ------------------------------------------------------------------ economics

def test_control_recoveries_are_not_credited_to_the_agent():
    """
    Gross recovery counts customers who would have returned anyway. Only the
    difference against the control arm belongs to the system.
    """
    result = calculate_experiment_results(cohort(100, 40, 100, 25, cost=30))
    assert result["treatment_recovered"] == 40
    assert result["net_lift"] == pytest.approx(0.15)
    assert result["incremental_cases"] == pytest.approx(15)
    assert result["incremental_cases"] < result["treatment_recovered"]


def test_roi_is_computed_on_the_incremental_amount_not_the_gross():
    result = calculate_experiment_results(cohort(100, 40, 100, 25, cost=100))
    gross = result["treatment_gross_recovered_paise"]
    assert result["value_incremental_paise"] < gross
    assert result["roi"] == pytest.approx(
        result["value_incremental_paise"] / result["intervention_cost_paise"]
    )


def test_spend_is_only_counted_for_the_treatment_arm():
    cases = cohort(10, 5, 10, 2, cost=30)
    for c in cases:
        if c["arm"] == "control":
            c["intervention_cost_paise"] = 999   # must be ignored
    assert calculate_experiment_results(cases)["intervention_cost_paise"] == 300


def test_zero_spend_does_not_divide_by_zero():
    assert calculate_experiment_results(cohort(10, 5, 10, 2, cost=0))["roi"] == 0.0


# ------------------------------------------------------------------ breakdowns

def test_per_class_breakdown_separates_the_lanes():
    cases = (cohort(50, 30, 50, 10, rc="AUTO_RETRY")
             + cohort(50, 10, 50, 10, rc="SWITCH_METHOD"))
    rows = {r["recovery_class"]: r for r in per_class_breakdown(cases)}

    assert rows["AUTO_RETRY"]["net_lift"] == pytest.approx(0.40)
    assert rows["SWITCH_METHOD"]["net_lift"] == pytest.approx(0.0)
    assert not rows["SWITCH_METHOD"]["is_significant"]


def test_exceptions_are_grouped_by_reason_and_ranked_by_money():
    cases = [
        case("treatment", False, amount=500_000, reason="Customer revoked consent"),
        case("treatment", False, amount=100_000, reason="Attempt budget exhausted"),
        case("treatment", False, amount=100_000, reason="Attempt budget exhausted"),
        case("treatment", True, amount=900_000),
    ]
    rows = exception_report(cases)
    assert rows[0]["reason"] == "Customer revoked consent"
    assert rows[0]["amount_paise"] == 500_000
    assert sum(r["count"] for r in rows) == 3   # the recovered case is excluded


# ------------------------------------------------------------------ assignment

def test_arm_assignment_is_stable_for_an_id():
    assert assign_arm("order_0001") == assign_arm("order_0001")


def test_arm_assignment_lands_near_the_intended_split():
    arms = [assign_arm(f"order_{i:05d}") for i in range(4000)]
    control_share = arms.count("control") / len(arms)
    assert 0.17 < control_share < 0.23


def test_arm_assignment_does_not_depend_on_outcomes():
    """
    Hashing the id means the arm is fixed before anything is known about the
    case. Nobody can move a case between arms after seeing how it went.
    """
    assert assign_arm("order_0001") == assign_arm("order_0001")
    assert assign_arm("order_0002") in {"treatment", "control"}


# ------------------------------------------------- stratified assignment

def test_stratification_hits_the_split_exactly_on_a_small_cohort():
    """
    Per-id hashing gives 20% only in expectation. The 90 abandoned carts landed
    on 8 controls instead of 18, which widened that lane's interval until it
    could say nothing — a measurement problem created by the sampling rather
    than by the policy.
    """
    ids = [f"order_cart_{i:03d}" for i in range(90)]
    arms = assign_arms(ids)
    controls = sum(1 for a in arms.values() if a == "control")
    assert controls == 18


def test_stratified_assignment_is_still_reproducible():
    ids = [f"order_{i:04d}" for i in range(200)]
    assert assign_arms(ids) == assign_arms(ids)
    # And independent of the order they are handed over in.
    assert assign_arms(ids) == assign_arms(list(reversed(ids)))


def test_stratified_assignment_covers_every_id_exactly_once():
    ids = [f"inv_{i:03d}" for i in range(80)]
    arms = assign_arms(ids)
    assert set(arms) == set(ids)
    assert set(arms.values()) == {"treatment", "control"}
