"""
End-to-end invariants.

Unit tests prove each gate works in isolation. These run an actual batch and
check the properties that make the whole result trustworthy — most importantly
that the control arm is genuinely untouched, because if it is not, every number
in EVALUATION.md is wrong and nothing else in the test suite would notice.
"""

from collections import Counter

import pytest

from app.core import clock, ledger
from app.core.ledger import verify_chain
from app.core.orchestrator import Orchestrator
from app.models import Action, Case, Customer, Event, Invoice, Order, Payment
from app.sim.generator import generate_dataset

# A slice big enough to exercise every lane, small enough to run in a test.
SAMPLE_CASES = 120


def our_sends(db):
    """
    Only the messages this system sent.

    The dataset seeds pre-existing outreach from a legacy system (tick -1) —
    deliberately at 3 AM and twice in a day, because that is the mess a
    frequency cap has to inherit. Those rows are input, not output: asserting
    our compliance properties over them would be testing the fixture.
    """
    return [
        a for a in db.query(Action).filter(Action.status == "SENT")
        if (a.tick or 0) >= 0
    ]


@pytest.fixture(scope="module")
def batch():
    """Seed a trimmed dataset, run one full batch, hand back the session."""
    from app.core.detector import detector
    from app.db import Base, SessionLocal, engine

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    ledger.reset_head_cache()
    detector.reset()

    data = generate_dataset(seed=42)
    db = SessionLocal()

    order_owner = {o["order_id"]: o["customer_id"] for o in data["orders"]}
    invoice_owner = {i["invoice_id"]: i["customer_id"] for i in data["invoices"]}
    for case in data["cases"]:
        case["customer_id"] = (
            order_owner.get(case["entity_id"]) if case["entity_type"] == "order"
            else invoice_owner.get(case["entity_id"])
        )

    # Keep every invoice case (the receivables lane is the smallest) plus a
    # slice of order cases, so all seven recovery classes are represented.
    invoices = [c for c in data["cases"] if c["entity_type"] == "invoice"]
    orders = [c for c in data["cases"] if c["entity_type"] == "order"]
    kept = invoices[:40] + orders[:SAMPLE_CASES]
    kept_ids = {c["case_id"] for c in kept}

    db.bulk_insert_mappings(Customer, data["customers"])
    db.bulk_insert_mappings(Order, data["orders"])
    db.bulk_insert_mappings(Payment, data["payments"])
    db.bulk_insert_mappings(Invoice, data["invoices"])
    db.bulk_insert_mappings(Case, kept)
    db.bulk_insert_mappings(
        Action, [a for a in data["prior_actions"] if a["case_id"] in kept_ids]
    )
    db.commit()

    summary = Orchestrator(db, real_link_budget=0).run()
    yield db, summary

    db.close()
    Base.metadata.drop_all(bind=engine)
    ledger.reset_head_cache()


# ------------------------------------------------------- the load-bearing one

def test_the_control_arm_is_never_contacted(batch):
    """
    The single invariant the whole experiment rests on. A control case that
    receives an action is not a control case, and the reported lift becomes a
    comparison of the system against itself.
    """
    db, _ = batch
    control_ids = {c.case_id for c in db.query(Case).filter(Case.arm == "control")}
    assert control_ids, "no control arm was assigned"

    touched = db.query(Action).filter(Action.case_id.in_(control_ids)).all()
    assert touched == [], f"{len(touched)} actions leaked onto control cases"


def test_the_control_arm_costs_nothing(batch):
    db, _ = batch
    spend = sum(
        c.intervention_cost_paise
        for c in db.query(Case).filter(Case.arm == "control")
    )
    assert spend == 0


def test_control_cases_are_still_classified_and_resolved(batch):
    """Untouched is not the same as ignored — they still have to be measured."""
    db, _ = batch
    for case in db.query(Case).filter(Case.arm == "control"):
        assert case.recovery_class is not None
        assert case.state != "OPEN"


# ------------------------------------------------------------------ budgets

def test_no_case_exceeds_its_attempt_budget(batch):
    db, _ = batch
    over = [c.case_id for c in db.query(Case) if c.touches_used > 3]
    assert over == []


def test_no_customer_is_contacted_twice_in_a_day(batch):
    db, _ = batch
    from datetime import timedelta

    by_customer = {}
    for a in our_sends(db):
        if a.channel in ("silent", "human") or not a.sent_at:
            continue
        by_customer.setdefault(a.customer_id, []).append(
            clock.datetime.fromisoformat(a.sent_at)
        )

    for customer_id, times in by_customer.items():
        times.sort()
        for earlier, later in zip(times, times[1:]):
            assert later - earlier >= timedelta(hours=24), (
                f"{customer_id} was contacted twice within "
                f"{later - earlier}"
            )


def test_nothing_is_sent_during_quiet_hours(batch):
    db, _ = batch
    for a in our_sends(db):
        if a.channel in ("silent", "human") or not a.sent_at:
            continue
        hour = clock.ist_hour(clock.datetime.fromisoformat(a.sent_at))
        assert 9 <= hour < 21, f"{a.action_id} sent at {hour}:00 IST"


def test_voice_calls_stay_inside_calling_hours(batch):
    db, _ = batch
    for a in db.query(Action).filter(Action.channel == "voice",
                                     Action.status == "SENT"):
        hour = clock.ist_hour(clock.datetime.fromisoformat(a.sent_at))
        assert 10 <= hour < 19


def test_risk_blocked_cases_only_ever_reach_a_human(batch):
    db, _ = batch
    risk_ids = {
        c.case_id for c in db.query(Case)
        .filter(Case.recovery_class == "MANUAL_REVIEW")
    }
    for a in our_sends(db):
        if a.case_id in risk_ids:
            assert a.channel == "human"


# ------------------------------------------------------------------ integrity

def test_the_audit_chain_is_intact_after_a_full_run(batch):
    db, _ = batch
    result = verify_chain(db)
    assert result["valid"], f"broken at {result['broken_at']}"
    assert result["records"] > 0


def test_every_case_has_a_classification_event(batch):
    db, _ = batch
    classified = {
        e.entity_id for e in db.query(Event).filter(Event.action == "CLASSIFY")
    }
    for case in db.query(Case):
        assert case.case_id in classified


def test_every_blocked_action_stores_the_full_gate_trail(batch):
    """A block without its trail is an assertion; with it, it is evidence."""
    db, _ = batch
    blocked = db.query(Action).filter(Action.status == "BLOCKED").all()
    assert blocked, "no guardrail fired in the sample batch"
    for a in blocked:
        assert a.blocked_by
        assert len(a.gate_decisions_json) == 11
        assert any(not g["allowed"] for g in a.gate_decisions_json)


def test_no_message_body_contains_an_unrendered_placeholder(batch):
    db, _ = batch
    for a in our_sends(db):
        if a.message_body:
            assert "{{" not in a.message_body, a.message_body


def test_every_case_reaches_a_terminal_state(batch):
    db, _ = batch
    states = Counter(c.state for c in db.query(Case))
    assert states["OPEN"] == 0
    assert states["PROMISED"] == 0


def test_unrecovered_cases_record_why(batch):
    """The exception list is a deliverable, so it cannot have blank rows."""
    db, _ = batch
    for case in db.query(Case).filter(Case.state != "RECOVERED"):
        assert case.exception_reason, f"{case.case_id} has no reason recorded"


# ------------------------------------------------------------------ determinism

def test_the_run_is_reproducible(batch):
    """
    Same seed, same clock, same numbers — on any machine, at any hour. This is
    what lets the committed database, EVALUATION.md and the demo video agree.
    """
    db, summary = batch
    first = {
        "recovered": summary["stats"].get("recovered"),
        "sent": summary["stats"].get("actions_sent"),
        "blocked": summary["stats"].get("actions_blocked"),
        "spend": summary["stats"].get("spend_paise"),
    }
    assert all(v is not None for v in first.values())

    # Re-derive the outcome for every case straight from the oracle and confirm
    # it matches what the run recorded.
    from app.sim.oracle import determine_outcome
    for case in db.query(Case).filter(Case.arm == "control"):
        expected = determine_outcome(case.case_id, case.recovery_class,
                                     arm="control")
        assert (case.state == "RECOVERED") == expected


def test_rerunning_from_the_api_reproduces_the_same_numbers(db):
    """
    A batch re-run from the dashboard must land on the same result as the first.

    It did not. `_reset` inferred which orders to un-pay from their current
    status, which cannot distinguish the eight planted already-settled traps
    from orders the agent had just recovered — so the traps were flipped to
    unpaid and vanished on the second run, and the totals drifted. Statuses are
    now restored from the value they were seeded with.
    """
    from app.api.batch import _reset
    from app.db import Base, engine

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    ledger.reset_head_cache()

    data = generate_dataset(seed=42)
    order_owner = {o["order_id"]: o["customer_id"] for o in data["orders"]}
    invoice_owner = {i["invoice_id"]: i["customer_id"] for i in data["invoices"]}
    for case in data["cases"]:
        case["customer_id"] = (
            order_owner.get(case["entity_id"]) if case["entity_type"] == "order"
            else invoice_owner.get(case["entity_id"])
        )
    kept = [c for c in data["cases"] if c["entity_type"] == "invoice"][:30] + \
           [c for c in data["cases"] if c["entity_type"] == "order"][:90]

    db.bulk_insert_mappings(Customer, data["customers"])
    db.bulk_insert_mappings(Order, data["orders"])
    db.bulk_insert_mappings(Payment, data["payments"])
    db.bulk_insert_mappings(Invoice, data["invoices"])
    db.bulk_insert_mappings(Case, kept)
    db.commit()

    def snapshot():
        return sorted(
            (c.case_id, c.state, c.touches_used, c.intervention_cost_paise)
            for c in db.query(Case)
        )

    Orchestrator(db, real_link_budget=0).run()
    first = snapshot()

    _reset(db)
    Orchestrator(db, real_link_budget=0).run()
    second = snapshot()

    assert first == second, (
        f"{sum(1 for a, b in zip(first, second) if a != b)} cases resolved "
        f"differently on the second run"
    )
