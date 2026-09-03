"""
Classifier tests.

Rule order is the thing most likely to break here, so it gets its own tests:
a risk-blocked payment must never fall through to an outreach branch no matter
what else is true about it.
"""

import pytest

from app.core.classifier import RULES, RecoveryClass, classify


def payment(**overrides) -> dict:
    base = {
        "attempt_no": 1,
        "issuer": "HDFC",
        "error_code": "BAD_REQUEST_ERROR",
        "error_source": "customer",
        "error_step": "payment_authentication",
        "error_reason": "payment_cancelled",
    }
    base.update(overrides)
    return base


def order(status="abandoned") -> dict:
    return {"entity_type": "order", "entity_status": status}


@pytest.mark.parametrize("reason,source,expected,rule", [
    ("issuer_down", "bank", RecoveryClass.AUTO_RETRY, "R-05"),
    ("gateway_technical_error", "gateway", RecoveryClass.AUTO_RETRY, "R-05"),
    ("payment_timeout", "bank", RecoveryClass.AUTO_RETRY, "R-05"),
    ("insufficient_funds", "bank", RecoveryClass.RETRY_TIMED, "R-06"),
    ("invalid_vpa", "customer", RecoveryClass.SWITCH_METHOD, "R-07"),
    ("card_expired", "customer", RecoveryClass.SWITCH_METHOD, "R-07"),
    ("card_declined_by_issuer", "bank", RecoveryClass.SWITCH_METHOD, "R-07"),
    ("payment_cancelled", "customer", RecoveryClass.NUDGE_CUSTOMER, "R-09"),
    ("authentication_failed", "customer", RecoveryClass.NUDGE_CUSTOMER, "R-09"),
    ("payment_blocked_by_risk", "internal", RecoveryClass.MANUAL_REVIEW, "R-03"),
    ("account_blocked", "internal", RecoveryClass.MANUAL_REVIEW, "R-03"),
    ("mandate_revoked", "customer", RecoveryClass.MANDATE_REPAIR, "R-04"),
    ("mandate_expired", "customer", RecoveryClass.MANDATE_REPAIR, "R-04"),
    ("refund_issued", "business", RecoveryClass.DEAD, "R-02"),
])
def test_each_razorpay_failure_reason_routes_somewhere_specific(
        reason, source, expected, rule):
    result = classify(order(), [payment(error_reason=reason, error_source=source)])
    assert result.recovery_class is expected
    assert result.rule_id == rule
    assert result.confidence == "deterministic"


def test_an_already_paid_order_is_dead_regardless_of_why_it_failed():
    result = classify(order(status="paid"),
                      [payment(error_reason="insufficient_funds")])
    assert result.recovery_class is RecoveryClass.DEAD
    assert result.rule_id == "R-01"


def test_risk_blocks_outrank_every_outreach_branch():
    """
    R-03 sits above every routing rule on purpose. A payment blocked by the risk
    engine that also looks like a customer-source failure must land in the
    human queue, not in a WhatsApp campaign.
    """
    result = classify(order(),
                      [payment(error_source="customer",
                               error_reason="payment_blocked_by_risk")])
    assert result.recovery_class is RecoveryClass.MANUAL_REVIEW


def test_classification_follows_the_latest_attempt():
    """A customer who retried with a different method changed the problem."""
    attempts = [
        payment(attempt_no=1, error_reason="insufficient_funds", error_source="bank"),
        payment(attempt_no=2, error_reason="invalid_vpa", error_source="customer"),
    ]
    assert classify(order(), attempts).recovery_class is RecoveryClass.SWITCH_METHOD
    # Order of the input list must not matter.
    assert classify(order(), list(reversed(attempts))).recovery_class \
        is RecoveryClass.SWITCH_METHOD


def test_invoices_route_to_the_receivables_ladder():
    result = classify({"entity_type": "invoice", "days_overdue": 12}, [])
    assert result.recovery_class is RecoveryClass.RECEIVABLE_CHASE
    assert result.rule_id == "R-08"


def test_an_unrecognised_failure_goes_to_a_human_rather_than_a_guess():
    result = classify(order(), [payment(error_source="business",
                                        error_reason="something_new_from_razorpay")])
    assert result.recovery_class is RecoveryClass.MANUAL_REVIEW
    assert result.rule_id == "R-DEFAULT"


def test_an_order_with_no_payment_attempt_is_an_abandoned_cart():
    """
    The third lane in the brief's scope line. There is no error taxonomy to
    route on because nothing was ever attempted — no failure to diagnose and
    nothing to retry, only intent that did not convert.
    """
    result = classify(order(), [])
    assert result.recovery_class is RecoveryClass.CHECKOUT_ABANDONED
    assert result.rule_id == "R-10"


def test_a_revoked_mandate_is_repaired_rather_than_written_off():
    """
    Retrying a revoked mandate is guaranteed to fail and would spend one of the
    three attempts proving it. Re-authorising is a different action, not the
    absence of one — treating this as DEAD wrote off recoverable subscription
    revenue.
    """
    result = classify(order(), [payment(error_reason="mandate_revoked")])
    assert result.recovery_class is RecoveryClass.MANDATE_REPAIR
    assert result.rule_id == "R-04"


def test_an_already_paid_cart_is_still_dead_not_abandoned():
    """R-01 outranks R-10: a settled order is never chased, attempts or not."""
    assert classify(order(status="paid"), []).recovery_class is RecoveryClass.DEAD


def test_every_rule_records_why_it_fired():
    """The rationale is what the LLM narrates and the audit trail stores."""
    for rule_id, _, _, _ in RULES:
        assert rule_id.startswith("R-")

    result = classify(order(), [payment(error_reason="insufficient_funds",
                                        error_source="bank")])
    assert result.rationale_facts["rule"] == "R-06"
    assert result.rationale_facts["why"]
    assert result.rationale_facts["error_source"] == "bank"
    assert result.rationale_facts["issuer"] == "HDFC"
