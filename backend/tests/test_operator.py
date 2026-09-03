"""
The human-review queue and what a person may do to it.

The first test in this file is the one that matters. Everything else is
plumbing next to it: an operator who works a control-arm case destroys the
experiment, and afterwards the damage is indistinguishable from the policy
having worked.
"""

import pytest
from fastapi.testclient import TestClient

from app.core import ledger
from app.core.operator import ACTIONS, OperatorError, act
from app.core.queue import break_even_paise, economics, queue
from app.main import app
from app.models import Case, Event


@pytest.fixture(scope="module")
def worked_db():
    """One completed batch, kept for the module."""
    from app.core.detector import detector
    from app.core.orchestrator import Orchestrator
    from app.db import Base, SessionLocal, engine
    from app.models import Action, Customer, Invoice, Order, Payment
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

    kept = [c for c in data["cases"] if c["entity_type"] == "invoice"][:40] + \
           [c for c in data["cases"] if c["entity_type"] == "order"][:320]
    kept_ids = {c["case_id"] for c in kept}

    db = SessionLocal()
    db.bulk_insert_mappings(Customer, data["customers"])
    db.bulk_insert_mappings(Order, data["orders"])
    db.bulk_insert_mappings(Payment, data["payments"])
    db.bulk_insert_mappings(Invoice, data["invoices"])
    db.bulk_insert_mappings(Case, kept)
    db.bulk_insert_mappings(
        Action, [a for a in data["prior_actions"] if a["case_id"] in kept_ids])
    db.commit()

    Orchestrator(db, real_link_budget=0).run()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)
        ledger.reset_head_cache()
        detector.reset()


def a_case(db, arm="treatment", state=None, recovery_class="MANUAL_REVIEW"):
    q = db.query(Case).filter(Case.recovery_class == recovery_class,
                              Case.arm == arm)
    if state:
        q = q.filter(Case.state == state)
    case = q.first()
    if case is None:
        pytest.skip(f"no {arm} {recovery_class} case in state {state}")
    return case


# ============================================================ the guard

def test_an_operator_cannot_work_a_control_case(worked_db):
    """
    The whole experiment rests on 163 cases nobody touched. One operator
    working the queue would destroy it silently, and afterwards it would look
    exactly like the policy having worked.
    """
    control = a_case(worked_db, arm="control")

    with pytest.raises(OperatorError, match="control arm"):
        act(worked_db, case_id=control.case_id, action="WRITE_OFF",
            operator="asha", reason="looked worth closing")

    worked_db.refresh(control)
    assert control.resolution != "WRITTEN_OFF_BY_OPERATOR"


def test_a_refused_control_action_leaves_no_trace(worked_db):
    """
    Refusing after writing the ledger entry would be worse than allowing it:
    the trail would claim an action that never happened.
    """
    control = a_case(worked_db, arm="control")
    before = worked_db.query(Event).count()

    with pytest.raises(OperatorError):
        act(worked_db, case_id=control.case_id, action="HOLD",
            operator="asha", reason="parking this")

    assert worked_db.query(Event).count() == before


def test_the_queue_never_lists_a_control_case(worked_db):
    """Belt as well as braces: the guard raises, and the list omits them."""
    listed = {r["case_id"] for r in queue(worked_db, limit=500,
                                          include_worked=True)}
    control = {c.case_id for c in worked_db.query(Case)
               .filter(Case.arm == "control")}
    assert not (listed & control)


# ==================================================== reasons and identity

def test_a_reason_is_required(worked_db):
    case = a_case(worked_db)
    for reason in ("", "   ", "x"):
        with pytest.raises(OperatorError, match="reason is required"):
            act(worked_db, case_id=case.case_id, action="HOLD",
                operator="asha", reason=reason)


def test_an_operator_id_is_required(worked_db):
    case = a_case(worked_db)
    with pytest.raises(OperatorError, match="operator id"):
        act(worked_db, case_id=case.case_id, action="HOLD",
            operator="  ", reason="parking pending legal")


def test_an_unknown_action_is_refused_with_the_valid_set(worked_db):
    case = a_case(worked_db)
    with pytest.raises(OperatorError, match="Valid actions"):
        act(worked_db, case_id=case.case_id, action="DELETE_EVERYTHING",
            operator="asha", reason="curious")


def test_an_unknown_case_is_refused(worked_db):
    with pytest.raises(OperatorError, match="No such case"):
        act(worked_db, case_id="case_nope", action="HOLD",
            operator="asha", reason="testing")


# ============================================================= the record

def test_every_action_lands_in_the_ledger_with_who_and_why(worked_db):
    case = a_case(worked_db, state="EXHAUSTED")
    before = worked_db.query(Event).count()

    result = act(worked_db, case_id=case.case_id, action="HOLD",
                 operator="asha", reason="customer disputing the charge")

    assert worked_db.query(Event).count() == before + 1

    row = (worked_db.query(Event)
           .order_by(Event.event_id.desc()).first())
    assert row.actor == "operator:asha"
    assert row.action == "OPERATOR_HOLD"
    assert row.entity_id == case.case_id
    assert row.payload_json["reason"] == "customer disputing the charge"
    assert row.this_hash == result["ledger_hash"]


def test_the_chain_still_verifies_after_an_operator_acts(worked_db):
    """
    An operator action is a real decision in the case's life. If it broke the
    chain, the audit trail would report tampering every time somebody did
    their job.
    """
    case = a_case(worked_db, state="EXHAUSTED")
    act(worked_db, case_id=case.case_id, action="HOLD",
        operator="ravi", reason="waiting on the risk team")

    assert ledger.verify_chain(worked_db)["valid"]


def test_the_entry_records_what_changed(worked_db):
    """
    Before and after, so a reviewer can see the effect rather than infer it
    from the current row.
    """
    case = a_case(worked_db, state="EXHAUSTED")
    was = case.state

    act(worked_db, case_id=case.case_id, action="WRITE_OFF",
        operator="asha", reason="customer is insolvent")

    row = worked_db.query(Event).order_by(Event.event_id.desc()).first()
    assert row.payload_json["before"]["state"] == was
    assert row.payload_json["after"]["state"] == "CLOSED"


# ============================================================ the effects

def test_a_write_off_closes_the_case_and_keeps_the_reason(worked_db):
    case = a_case(worked_db, state="EXHAUSTED")

    act(worked_db, case_id=case.case_id, action="WRITE_OFF",
        operator="asha", reason="disputed and not worth the argument")

    worked_db.refresh(case)
    assert case.state == "CLOSED"
    assert case.resolution == "WRITTEN_OFF_BY_OPERATOR"
    assert "disputed" in case.exception_reason


def test_paid_offline_is_recorded_but_not_credited_to_the_policy(worked_db):
    """
    The customer paid through a route the system never touched. Recording it is
    right; crediting it to the agent would inflate the measured lift.
    """
    case = a_case(worked_db, state="EXHAUSTED")

    act(worked_db, case_id=case.case_id, action="MARK_PAID_OFFLINE",
        operator="ravi", reason="bank transfer received this morning")

    worked_db.refresh(case)
    assert case.state == "RECOVERED"
    assert case.recovered_paise == case.amount_at_risk_paise

    row = worked_db.query(Event).order_by(Event.event_id.desc()).first()
    assert row.payload_json["counts_towards_lift"] is False


def test_approving_a_contact_records_a_judgement_and_sends_nothing(worked_db):
    """The same line the live webhook draws: decide, do not execute."""
    case = a_case(worked_db, state="EXHAUSTED")
    was = case.state

    result = act(worked_db, case_id=case.case_id, action="APPROVE_CONTACT",
                 operator="asha", reason="risk team cleared this customer")

    worked_db.refresh(case)
    assert case.state == was          # judgement recorded, case untouched
    assert result["executed"] is False


def test_a_closed_case_cannot_be_closed_again(worked_db):
    """Two contradictory outcomes in one trail is worse than a refusal."""
    case = a_case(worked_db, state="EXHAUSTED")
    act(worked_db, case_id=case.case_id, action="WRITE_OFF",
        operator="asha", reason="first close")

    with pytest.raises(OperatorError, match="already CLOSED"):
        act(worked_db, case_id=case.case_id, action="MARK_PAID_OFFLINE",
            operator="ravi", reason="second close")


# ========================================================== the economics

def test_break_even_is_computed_from_cost_and_lift():
    """
    Fifty rupees of attention against a two percent lift needs Rs 2,500 at
    risk before the call can pay for itself. Asserted from the inputs rather
    than hardcoded, so it moves when a merchant changes the price.
    """
    from app.core import config
    from app.sim import oracle

    cost = config.active().tier_cost_paise[4]
    lift = oracle.TIER_MARGINAL_LIFT[("MANUAL_REVIEW", 4)]

    assert break_even_paise() == int(cost / lift)


def test_a_rung_with_no_modelled_lift_has_no_threshold():
    """None, rather than a threshold of zero, which would mean "always call"."""
    assert break_even_paise(recovery_class="DEAD", tier=4) is None


def test_the_economics_separate_what_is_projected_from_what_was_measured(worked_db):
    """
    The distinction the whole page rests on: expected return is our
    assumptions, measured lift is what the batch could see, and they are not
    the same kind of number.
    """
    e = economics(worked_db)

    assert e["expected_incremental_paise"] > 0      # a projection
    assert "ci_lower" in e and "ci_upper" in e      # a measurement
    assert e["required_n_per_arm"] > e["cases"]     # why they disagree


def test_the_economics_do_not_claim_the_lane_loses_money(worked_db):
    """
    The correction this module exists to make. "Cannot be measured at this
    size" is a different and more defensible claim than "is not paying for
    itself", and the wording has to keep saying so.
    """
    e = economics(worked_db)

    assert not e["is_significant"]
    assert e["expected_incremental_paise"] > e["spend_paise"]
    assert "cannot be measured" in e["reading"]


def test_the_queue_flags_cases_below_break_even(worked_db):
    threshold = break_even_paise()
    for row in queue(worked_db, limit=500, include_worked=True):
        assert row["below_break_even"] == (
            row["amount_at_risk_paise"] < threshold)


def test_the_queue_is_ordered_by_money_at_risk(worked_db):
    amounts = [r["amount_at_risk_paise"]
               for r in queue(worked_db, limit=500, include_worked=True)]
    assert amounts == sorted(amounts, reverse=True)


# ============================================================ the endpoint

def test_the_endpoint_serves_the_queue_and_its_economics(worked_db):
    with TestClient(app) as client:
        body = client.get("/api/queue").json()

    assert body["queue"]
    assert body["economics"]["break_even_paise"]
    assert {a["action"] for a in body["actions"]} == set(ACTIONS)


def test_the_endpoint_refuses_a_control_case_with_a_422(worked_db):
    control = a_case(worked_db, arm="control")

    with TestClient(app) as client:
        response = client.post(
            f"/api/queue/{control.case_id}/act",
            json={"action": "WRITE_OFF", "operator": "asha",
                  "reason": "should not be possible"})

    assert response.status_code == 422
    assert "control arm" in response.json()["detail"]


def test_the_endpoint_refuses_a_missing_reason_with_a_422(worked_db):
    case = a_case(worked_db, state="EXHAUSTED")

    with TestClient(app) as client:
        response = client.post(
            f"/api/queue/{case.case_id}/act",
            json={"action": "HOLD", "operator": "asha", "reason": ""})

    assert response.status_code == 422
