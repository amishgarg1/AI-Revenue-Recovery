"""
The sensitivity sweep.

What is being tested is not "the function returns numbers". It is the two
properties the analysis depends on: that perturbing the oracle cannot change
the recorded decisions, and that the sweep reproduces the committed result at
factor 1.0. If either fails, every figure the sweep reports is meaningless.
"""

import pytest

from app.analytics.sensitivity import (
    SWEEP, breaking_point, evaluate, observed_run, sensitivity_report,
    sweep_parameter,
)
from app.sim import oracle


@pytest.fixture(scope="module")
def batch_db():
    """
    One completed batch, kept for the whole module.

    Sized to keep the suite fast, which means the numbers here are not the
    committed ones. Nothing below asserts a specific lift for that reason -
    these tests are about properties that must hold at any sample size.
    """
    from app.core import ledger
    from app.core.detector import detector
    from app.core.orchestrator import Orchestrator
    from app.db import Base, SessionLocal, engine
    from app.models import Action, Case, Customer, Invoice, Order, Payment
    from app.sim.generator import generate_dataset

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    ledger.reset_head_cache()
    detector.reset()

    data = generate_dataset(seed=42)
    order_owner = {o["order_id"]: o["customer_id"] for o in data["orders"]}
    invoice_owner = {i["invoice_id"]: i["customer_id"] for i in data["invoices"]}
    for case in data["cases"]:
        case["customer_id"] = (
            order_owner.get(case["entity_id"]) if case["entity_type"] == "order"
            else invoice_owner.get(case["entity_id"])
        )

    # Every invoice case plus a slice of order cases, so all the recovery
    # classes are represented rather than only the common ones.
    invoices = [c for c in data["cases"] if c["entity_type"] == "invoice"]
    orders = [c for c in data["cases"] if c["entity_type"] == "order"]
    kept = invoices[:60] + orders[:340]
    kept_ids = {c["case_id"] for c in kept}

    db = SessionLocal()
    db.bulk_insert_mappings(Customer, data["customers"])
    db.bulk_insert_mappings(Order, data["orders"])
    db.bulk_insert_mappings(Payment, data["payments"])
    db.bulk_insert_mappings(Invoice, data["invoices"])
    db.bulk_insert_mappings(Case, kept)
    db.bulk_insert_mappings(
        Action, [a for a in data["prior_actions"] if a["case_id"] in kept_ids]
    )
    db.commit()

    Orchestrator(db, real_link_budget=0).run()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)
        ledger.reset_head_cache()
        detector.reset()


@pytest.fixture(scope="module")
def rows(batch_db):
    return observed_run(batch_db)


@pytest.fixture(scope="module")
def marginal_sweep(rows):
    return sweep_parameter(rows, "Every marginal lift per rung", "marginal_all")


# --------------------------------------------------------------- the premise

import pathlib

CORE = pathlib.Path(__file__).resolve().parents[1] / "app" / "core"

# The orchestrator is the one module allowed to touch the oracle, because it is
# the thing that asks what happened after it has already decided and acted -
# the same call it would make to a payment gateway. Everything that makes a
# decision must be clean.
DECISION_MODULES = ["classifier.py", "ladder.py", "policy.py", "detector.py",
                    "clock.py", "ledger.py", "live.py"]

# The only oracle functions the orchestrator may call: all of them report an
# outcome. None of them can influence what the agent chooses to do next.
OUTCOME_ONLY = {"determine_outcome", "makes_promise", "keeps_promise",
                "control_resolution_tick"}


def test_no_decision_module_reads_the_oracle():
    """
    The premise of the whole analysis. If a decision module imported the
    oracle, perturbing a base rate could change which messages were sent, and
    a sweep would stop being a recomputation over a fixed run.
    """
    offenders = [
        name for name in DECISION_MODULES
        if "oracle" in (CORE / name).read_text(encoding="utf-8")
    ]
    assert not offenders, f"decision modules referencing the oracle: {offenders}"


def test_the_orchestrator_asks_the_oracle_only_what_happened():
    """
    It does import the oracle - it has to, something must record outcomes. What
    it must never do is let an oracle value reach a decision, so the set of
    functions it calls is pinned. A new call here is not automatically wrong,
    but it needs looking at.
    """
    import re

    source = (CORE / "orchestrator.py").read_text(encoding="utf-8")
    called = set(re.findall(r"oracle\.(\w+)", source))
    assert called <= OUTCOME_ONLY, f"unexpected oracle calls: {called - OUTCOME_ONLY}"


def test_control_cases_carry_no_delivered_tiers(rows):
    """A control case was never contacted, so it can have no touches."""
    assert all(r["tiers"] == () for r in rows if r["arm"] == "control")


def test_treatment_cases_did_receive_touches(rows):
    """Guards against an empty join quietly making every arm look identical."""
    touched = [r for r in rows if r["arm"] != "control" and r["tiers"]]
    assert len(touched) > 100, len(touched)


# ------------------------------------------------------- reproducing the run

def test_factor_one_reproduces_the_committed_result(rows, batch_db):
    """
    The sweep recomputes outcomes rather than reading them, so at factor 1.0 it
    must land exactly on the number the batch recorded. Any drift here means
    the recomputation and the orchestrator disagree about the model.
    """
    from app.analytics.experiment import calculate_experiment_results
    from app.api.cases import _row
    from app.models import Case

    recomputed = evaluate(
        rows,
        oracle.NO_INTERVENTION_BASELINE,
        oracle.TIER_MARGINAL_LIFT,
        oracle.MAX_RECOVERY_PROBABILITY,
    )
    recorded = calculate_experiment_results(
        [_row(c) for c in batch_db.query(Case)]
    )

    assert recomputed["treatment_rate"] == pytest.approx(
        recorded["treatment_rate"], abs=0.001)
    assert recomputed["control_rate"] == pytest.approx(
        recorded["control_rate"], abs=0.001)
    assert recomputed["net_lift"] == pytest.approx(
        recorded["net_lift"], abs=0.001)


def test_the_sweep_does_not_mutate_the_oracle(rows):
    """
    A sweep that left the module's constants changed would poison every later
    query in the same process - the dashboard would start reporting whatever
    the last perturbation happened to be.
    """
    before = dict(oracle.NO_INTERVENTION_BASELINE), dict(oracle.TIER_MARGINAL_LIFT)
    sweep_parameter(rows, "Every marginal lift per rung", "marginal_all")
    assert (oracle.NO_INTERVENTION_BASELINE, oracle.TIER_MARGINAL_LIFT) == before


# ------------------------------------------------------------- the behaviour

def test_more_effective_interventions_produce_more_lift(rows):
    """Sanity: the model should be monotonic in the marginal lifts."""
    sweep = sweep_parameter(rows, "Every marginal lift per rung", "marginal_all")
    lifts = [p["net_lift"] for p in sweep["points"]]
    assert lifts == sorted(lifts), lifts


def test_baselines_cut_both_arms(rows):
    """
    Raising the no-intervention baseline lifts the control arm too, so it
    cannot simply inflate the measured lift the way a marginal lift does. This
    is why the baseline is a far smaller lever than a reviewer expects.
    """
    sweep = sweep_parameter(rows, "Every no-intervention baseline", "baseline_all")
    marginal = sweep_parameter(rows, "Every marginal lift", "marginal_all")
    assert sweep["swing_pp"] < marginal["swing_pp"]


def test_a_class_with_no_cases_cannot_move_the_answer(rows):
    """DEAD has a zero baseline and no rungs; scaling it must change nothing."""
    sweep = sweep_parameter(rows, "DEAD baseline", "baseline_one", key="DEAD")
    assert sweep["swing_pp"] == 0.0
    assert sweep["impact"] == "negligible"


# ---------------------------------------------------------- breaking point

def _bracket(sweep):
    """The coarse pair the bisection must land between, or None."""
    failed = [p["factor"] for p in sweep["points"] if not p["is_significant"]]
    if not failed:
        return None
    held = [p["factor"] for p in sweep["points"]
            if p["is_significant"] and p["factor"] > max(failed)]
    return (max(failed), min(held)) if held else None


def test_the_breaking_point_is_inside_its_bracket(rows, marginal_sweep):
    """
    The bisected figure has to sit between the coarse factor that failed and
    the next one that held, or the bracket was wrong.
    """
    bracket = _bracket(marginal_sweep)
    if bracket is None:
        pytest.skip("no significance boundary inside the swept range")

    low, high = bracket
    assert low < breaking_point(rows, marginal_sweep) <= high


def test_significance_actually_flips_across_the_breaking_point(rows, marginal_sweep):
    """
    The number is only meaningful if the conclusion really does change there.
    Checked from both sides rather than trusting the search.
    """
    if _bracket(marginal_sweep) is None:
        pytest.skip("no significance boundary inside the swept range")

    point = breaking_point(rows, marginal_sweep)

    def at(factor):
        return evaluate(
            rows, oracle.NO_INTERVENTION_BASELINE,
            {k: v * factor for k, v in oracle.TIER_MARGINAL_LIFT.items()},
            oracle.MAX_RECOVERY_PROBABILITY)["is_significant"]

    assert not at(point - 0.02)
    assert at(point + 0.02)


def test_a_parameter_that_never_breaks_reports_no_point(rows):
    sweep = sweep_parameter(rows, "DEAD baseline", "baseline_one", key="DEAD")
    assert sweep["breaks_at"] is None
    assert breaking_point(rows, sweep) is None


# ---------------------------------------------------------------- the report

def test_the_report_ranks_by_swing(batch_db):
    report = sensitivity_report(batch_db)
    swings = [p["swing_pp"] for p in report["parameters"]]
    assert swings == sorted(swings, reverse=True)


def test_the_report_names_what_would_have_to_be_wrong(batch_db):
    """
    The finding a reviewer should leave with: a number saying how far off the
    assumptions have to be before the conclusion stops holding. Whether any
    assumption breaks it depends on the run, so what is asserted is that the
    report and its own summary flag cannot disagree.
    """
    report = sensitivity_report(batch_db)

    assert report["conclusion_holds"] is (not report["breakers"])
    for b in report["breakers"]:
        assert 0 < b["breaking_point"] <= max(SWEEP)
        assert b["wrong_by_pct"] is not None
        assert b["label"]


def test_every_parameter_is_swept_at_every_factor(batch_db):
    report = sensitivity_report(batch_db)
    for p in report["parameters"]:
        assert [x["factor"] for x in p["points"]] == list(SWEEP)


# --------------------------------------------------------------- the memo

def test_the_report_is_cached_between_calls(batch_db):
    """
    Six seconds a request is fine once and unacceptable on every dashboard
    load. Identity rather than equality, so this fails if the memo silently
    recomputes.
    """
    from app.analytics import sensitivity

    sensitivity.clear_cache()
    first = sensitivity_report(batch_db)
    assert sensitivity_report(batch_db) is first


def test_a_new_run_invalidates_the_cache(batch_db):
    """
    The failure mode that matters: serving last run's answer after a fresh
    batch. Deleting a delivered action changes the run, so the fingerprint must
    change with it.
    """
    from app.analytics import sensitivity
    from app.models import Action

    sensitivity.clear_cache()
    before = sensitivity_report(batch_db)

    doomed = (batch_db.query(Action)
              .filter(Action.status == "SENT").first())
    batch_db.delete(doomed)
    batch_db.commit()

    after = sensitivity_report(batch_db)
    assert after is not before

    batch_db.rollback()


def test_passing_rows_bypasses_the_cache(rows):
    """The escape hatch the sweep helpers rely on."""
    from app.analytics import sensitivity

    sensitivity.clear_cache()
    a = sensitivity_report(None, rows=rows)
    b = sensitivity_report(None, rows=rows)
    assert a is not b
    assert not sensitivity._cache
