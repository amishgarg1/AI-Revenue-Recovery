"""
The live webhook path.

The claim being tested is not "the endpoint returns 200". It is that a real
Razorpay payload reaches the same classifier, the same ladder and the same
eleven gates the batch uses, and that a webhook nobody signed cannot be passed
off as one that was.
"""

import hashlib
import hmac
import json
import os

import pytest
from fastapi.testclient import TestClient

from app.core.live import case_from_webhook, decide, verify_live_chain
from app.db import Base, SessionLocal, engine
from app.main import app
from app.models import LiveDecision


def razorpay_payload(**overrides):
    """
    A `payment.failed` webhook shaped the way Razorpay actually sends one.

    The error taxonomy is the interesting part: `error_source` and
    `error_step` are what the classifier routes on, and they arrive from
    Razorpay without translation.
    """
    entity = {
        "id": "pay_NqRs4vXyZ12345",
        "entity": "payment",
        "amount": 4_50_000,
        "currency": "INR",
        "status": "failed",
        "order_id": "order_NqRs4vXyZ00001",
        "method": "card",
        "bank": "HDFC",
        "card_id": "card_NqRs4vXyZ99999",
        "error_code": "BAD_REQUEST_ERROR",
        "error_description": "Your card was declined by the issuing bank.",
        "error_source": "bank",
        "error_step": "authorization",
        "error_reason": "card_declined_by_issuer",
    }
    entity.update(overrides)
    return {
        "entity": "event",
        "account_id": "acc_NqRs4vXyZ",
        "event": "payment.failed",
        "contains": ["payment"],
        "payload": {"payment": {"entity": entity}},
        "created_at": 1_756_000_000,
    }


@pytest.fixture
def client():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        db.query(LiveDecision).delete()
        db.commit()
    finally:
        db.close()
    with TestClient(app) as c:
        yield c


@pytest.fixture
def signed(monkeypatch):
    secret = "whsec_test_do_not_use"
    monkeypatch.setenv("RZP_WEBHOOK_SECRET", secret)

    def sign(payload):
        body = json.dumps(payload).encode()
        mac = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        return body, mac

    return sign


@pytest.fixture(autouse=True)
def no_secret_by_default(monkeypatch):
    """The demo has to work with no keys, so that is the default here too."""
    monkeypatch.delenv("RZP_WEBHOOK_SECRET", raising=False)


# ------------------------------------------------------------------ parsing

def test_a_real_payload_needs_no_translation_layer():
    """
    Razorpay nests the payment at payload.payment.entity, and its error fields
    are already the ones the classifier reads.
    """
    parsed = case_from_webhook(razorpay_payload())

    assert parsed["entity"]["id"] == "pay_NqRs4vXyZ12345"
    assert parsed["case"]["entity_id"] == "order_NqRs4vXyZ00001"
    assert parsed["case"]["amount_at_risk_paise"] == 4_50_000
    assert parsed["payment"]["error_reason"] == "card_declined_by_issuer"
    assert parsed["payment"]["error_source"] == "bank"
    assert parsed["payment"]["error_step"] == "authorization"


# ------------------------------------------------- same logic as the batch

def test_the_webhook_routes_the_way_the_classifier_does(client):
    """A card declined by the issuer is a method problem, not a retry."""
    r = client.post("/api/live/payment-failed", json=razorpay_payload()).json()

    assert r["recovery_class"] == "SWITCH_METHOD"
    assert r["rule_id"]
    assert r["action"]["tier"] == 1


def test_an_infrastructure_failure_routes_to_a_silent_retry(client):
    r = client.post("/api/live/payment-failed", json=razorpay_payload(
        error_reason="issuer_down", error_source="bank", error_step="authorization",
    )).json()

    assert r["recovery_class"] in ("AUTO_RETRY", "RETRY_TIMED")


def test_a_risk_block_is_never_auto_contacted(client):
    """The gates, not just the classifier, have to agree."""
    r = client.post("/api/live/payment-failed", json=razorpay_payload(
        error_reason="payment_blocked_by_risk", error_source="business",
        error_step="authorization",
    )).json()

    assert r["recovery_class"] == "MANUAL_REVIEW"
    assert r["action"]["tier"] == 4          # a person, not a message


def test_all_eleven_gates_run_on_a_live_event(client):
    """
    Not just the one that blocks. The batch records the whole trail after a
    refusal and so does this - a live decision you cannot audit in full is
    not the same decision.
    """
    r = client.post("/api/live/payment-failed", json=razorpay_payload()).json()

    assert len(r["gate_trail"]) == 11
    assert [g["gate_id"] for g in r["gate_trail"]] == [
        f"G{n:02d}" for n in range(1, 12)
    ]


def test_every_gate_explains_itself_readably(client):
    """
    The trail is read by a person. G10 reported "Case is None" on live events
    because a webhook case had no state - accurate about the data and no use
    to anyone reading the refusal.
    """
    r = client.post("/api/live/payment-failed", json=razorpay_payload()).json()

    for gate in r["gate_trail"]:
        assert gate["detail"], gate
        assert "None" not in gate["detail"], gate


def test_a_refusal_names_the_first_failing_gate(client):
    r = client.post("/api/live/payment-failed", json=razorpay_payload()).json()

    first_fail = next((g["gate_id"] for g in r["gate_trail"] if not g["allowed"]),
                      None)
    assert r["blocked_by"] == first_fail


def test_a_terminal_case_spends_nothing(client):
    """DEAD has no rung. Reporting that is the point of having the class."""
    r = client.post("/api/live/payment-failed", json=razorpay_payload(
        error_reason="refund_issued",
    )).json()

    assert r["recovery_class"] == "DEAD"
    assert r["action"] is None
    assert r["reason_code"] == "NO_ACTION"


def test_it_decides_but_never_sends(client):
    """Executing means a real message and a real charge."""
    r = client.post("/api/live/payment-failed", json=razorpay_payload()).json()
    assert r["executed"] is False


# ----------------------------------------------------------------- security

def test_a_valid_signature_is_accepted(client, signed):
    body, mac = signed(razorpay_payload())
    response = client.post(
        "/api/live/payment-failed", content=body,
        headers={"X-Razorpay-Signature": mac,
                 "Content-Type": "application/json"},
    )
    assert response.status_code == 200
    assert response.json()["signature_verified"] is True


def test_a_forged_signature_is_rejected(client, signed):
    body, _ = signed(razorpay_payload())
    response = client.post(
        "/api/live/payment-failed", content=body,
        headers={"X-Razorpay-Signature": "0" * 64,
                 "Content-Type": "application/json"},
    )
    assert response.status_code == 401


def test_a_tampered_body_is_rejected(client, signed):
    """
    The signature covers the body. Changing the amount after signing - the
    thing an attacker would actually do - must not verify.
    """
    body, mac = signed(razorpay_payload())
    tampered = body.replace(b'"amount": 450000', b'"amount": 1')

    response = client.post(
        "/api/live/payment-failed", content=tampered,
        headers={"X-Razorpay-Signature": mac,
                 "Content-Type": "application/json"},
    )
    assert response.status_code == 401


def test_an_unsigned_request_is_never_reported_as_verified(client):
    """
    With no secret configured the decision still runs, because the demo has to
    work without keys. What it must not do is imply the check happened.
    """
    r = client.post("/api/live/payment-failed", json=razorpay_payload()).json()

    assert r["signature_verified"] is False
    assert r["signature_checked"] is False


# ------------------------------------------------------- the separate book

def test_live_decisions_do_not_touch_the_simulation_ledger(client):
    """
    The committed evaluation is derived from `events`. If a live decision
    landed there, demonstrating the webhook once would move the published
    numbers and the run would stop being reproducible.
    """
    from app.models import Event

    db = SessionLocal()
    try:
        before = db.query(Event).count()
    finally:
        db.close()

    client.post("/api/live/payment-failed", json=razorpay_payload())

    db = SessionLocal()
    try:
        assert db.query(Event).count() == before
    finally:
        db.close()


def test_the_live_book_is_hash_chained_too(client):
    for _ in range(3):
        client.post("/api/live/payment-failed", json=razorpay_payload())

    db = SessionLocal()
    try:
        chain = verify_live_chain(db)
        assert chain["records"] == 3
        assert chain["valid"]
    finally:
        db.close()


def test_editing_a_live_decision_breaks_its_chain(client):
    """Same guarantee as the simulation ledger, verified the same way."""
    client.post("/api/live/payment-failed", json=razorpay_payload())
    client.post("/api/live/payment-failed", json=razorpay_payload())

    db = SessionLocal()
    try:
        row = db.query(LiveDecision).order_by(LiveDecision.decision_id).first()
        row.recovery_class = "AUTO_RETRY"
        db.commit()

        chain = verify_live_chain(db)
        assert not chain["valid"]
        assert chain["first_break"] == row.decision_id
    finally:
        db.close()


def test_the_decisions_endpoint_reports_its_own_chain(client):
    client.post("/api/live/payment-failed", json=razorpay_payload())
    r = client.get("/api/live/decisions").json()

    assert r["chain"]["valid"]
    assert len(r["decisions"]) == 1
    assert r["decisions"][0]["recovery_class"] == "SWITCH_METHOD"


# ---------------------------------------------------------------- liveness

def test_a_decision_is_fast_enough_to_be_synchronous(client):
    """
    A webhook handler that takes a second is a webhook handler that times out.
    The budget here is generous; the point is that no model call sits in the
    decision path.
    """
    r = client.post("/api/live/payment-failed", json=razorpay_payload()).json()
    assert r["latency_ms"] < 100, r["latency_ms"]


def test_a_malformed_body_is_a_400_not_a_500(client):
    response = client.post(
        "/api/live/payment-failed", content=b"not json",
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 400
