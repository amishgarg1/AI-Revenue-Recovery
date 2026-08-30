"""
Recoverability classification — a decision table, not a model.

Razorpay already tells you why a payment failed, in two fields that between
them answer the only question that matters:

    error_source  -> whose fault was it?   (bank | gateway | customer | internal)
    error_step    -> where did it break?   (initiation | authentication | ...)

A bank or gateway failure means the customer did nothing wrong, so retry
silently. A customer-source failure means only the customer can fix it, so a
retry is pointless and a nudge is the cheapest thing that can work. An internal
risk block means do not touch it at all.

We route on Razorpay's taxonomy rather than inventing our own, so every
decision here is traceable to a field the merchant can see in their dashboard.

Rule order is load-bearing. DEAD and MANUAL_REVIEW sit at the top so a
risk-blocked or already-settled case can never fall through into an outreach
branch, whatever else is true about it.
"""

from dataclasses import dataclass
from enum import Enum
from typing import List, Optional


class RecoveryClass(str, Enum):
    AUTO_RETRY = "AUTO_RETRY"
    RETRY_TIMED = "RETRY_TIMED"
    SWITCH_METHOD = "SWITCH_METHOD"
    NUDGE_CUSTOMER = "NUDGE_CUSTOMER"
    CHECKOUT_ABANDONED = "CHECKOUT_ABANDONED"
    MANDATE_REPAIR = "MANDATE_REPAIR"
    RECEIVABLE_CHASE = "RECEIVABLE_CHASE"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    DEAD = "DEAD"


@dataclass
class Classification:
    recovery_class: RecoveryClass
    rule_id: str
    confidence: str
    rationale_facts: dict


# Reason sets, named so the rules below read as sentences.
TERMINAL_REASONS = {"refund_issued", "order_cancelled"}
MANDATE_REASONS = {"mandate_revoked", "mandate_expired", "mandate_paused"}
RISK_REASONS = {"payment_blocked_by_risk", "account_blocked"}
INFRA_REASONS = {"issuer_down", "gateway_technical_error", "payment_timeout"}
METHOD_REASONS = {
    "invalid_vpa", "card_expired", "card_declined_by_issuer",
    "international_transaction_not_allowed", "incorrect_cvv", "limit_exceeded",
}


class CaseFacts:
    """The subset of a case the rules are allowed to look at."""

    def __init__(self, case: dict, payments: Optional[List[dict]] = None):
        self.entity_type = case.get("entity_type")
        self.entity_status = case.get("entity_status") or case.get("status")
        self.days_overdue = case.get("days_overdue")

        payments = payments or []
        self.attempt_count = len(payments)
        # Classification follows the *latest* attempt: if the customer retried
        # with a different method, the old failure is history.
        self.latest = (
            sorted(payments, key=lambda p: p.get("attempt_no", 0))[-1]
            if payments else None
        )

    @property
    def already_paid(self) -> bool:
        return self.entity_status == "paid"

    @property
    def error_reason(self) -> Optional[str]:
        return self.latest.get("error_reason") if self.latest else None

    @property
    def error_source(self) -> Optional[str]:
        return self.latest.get("error_source") if self.latest else None

    @property
    def error_step(self) -> Optional[str]:
        return self.latest.get("error_step") if self.latest else None

    @property
    def issuer(self) -> Optional[str]:
        return self.latest.get("issuer") if self.latest else None

    def as_facts(self) -> dict:
        return {
            "entity_type": self.entity_type,
            "entity_status": self.entity_status,
            "attempt_count": self.attempt_count,
            "error_source": self.error_source,
            "error_step": self.error_step,
            "error_reason": self.error_reason,
            "issuer": self.issuer,
            "days_overdue": self.days_overdue,
        }


# (rule_id, predicate, class, human-readable why)
#
# Evaluated top to bottom, first match wins, and the ids run in that order so a
# `rule_id` in the audit trail also tells you what was ruled out ahead of it.
RULES = [
    # --- hard stops, above every branch that could contact somebody ---------
    ("R-01", lambda f: f.already_paid, RecoveryClass.DEAD,
     "Already settled on another attempt - chasing it would risk a double charge"),

    ("R-02", lambda f: f.error_reason in TERMINAL_REASONS, RecoveryClass.DEAD,
     "Refunded or cancelled - there is no longer a debt to recover"),

    ("R-03", lambda f: f.error_reason in RISK_REASONS, RecoveryClass.MANUAL_REVIEW,
     "Blocked by the risk engine - a human decides, we never auto-contact"),

    # --- routed by Razorpay's failure taxonomy -----------------------------
    # A revoked mandate cannot be *retried*: the authorisation is gone, so every
    # attempt against it is guaranteed to fail and to burn an attempt from the
    # budget. But it can be *re-authorised*, which is a different action, not
    # the absence of one. Calling this DEAD was the conservative reading and
    # the wrong one - it wrote off recoverable subscription revenue instead of
    # asking for a new mandate.
    ("R-04", lambda f: f.error_reason in MANDATE_REASONS, RecoveryClass.MANDATE_REPAIR,
     "Mandate is gone - retrying is futile, but re-authorisation is not"),

    ("R-05", lambda f: f.error_source in {"bank", "gateway"}
             and f.error_reason in INFRA_REASONS, RecoveryClass.AUTO_RETRY,
     "Infrastructure failed, not the customer - retry silently once it is healthy"),

    ("R-06", lambda f: f.error_reason == "insufficient_funds", RecoveryClass.RETRY_TIMED,
     "The money was not there yet - retry near payday before spending on outreach"),

    ("R-07", lambda f: f.error_reason in METHOD_REASONS, RecoveryClass.SWITCH_METHOD,
     "This instrument cannot work - only a different method will"),

    # --- routed by what the entity is, when there is no failure to route on --
    ("R-08", lambda f: f.entity_type == "invoice", RecoveryClass.RECEIVABLE_CHASE,
     "B2B receivable - escalating reminder ladder, voice only if it is worth it"),

    ("R-09", lambda f: f.error_source == "customer", RecoveryClass.NUDGE_CUSTOMER,
     "The customer abandoned the flow - a reminder with a working link is enough"),

    # Nothing was ever attempted, so there is no error taxonomy to route on at
    # all. This is the third lane in the brief's own scope line, and it behaves
    # unlike every other class: no failure to diagnose, nothing to retry, only
    # intent that did not convert.
    ("R-10", lambda f: f.entity_type == "order" and f.attempt_count == 0,
     RecoveryClass.CHECKOUT_ABANDONED,
     "Cart left before any payment was attempted - intent, not failure"),
]

RULE_EXPLANATIONS = {rule_id: why for rule_id, _, _, why in RULES}
RULE_EXPLANATIONS["R-DEFAULT"] = (
    "No rule matched - routed to a human rather than guessed at"
)


def classify(case: dict, payments: Optional[List[dict]] = None) -> Classification:
    facts = CaseFacts(case, payments)

    for rule_id, predicate, recovery_class, why in RULES:
        if predicate(facts):
            rationale = facts.as_facts()
            rationale["rule"] = rule_id
            rationale["why"] = why
            return Classification(recovery_class, rule_id, "deterministic", rationale)

    rationale = facts.as_facts()
    rationale["rule"] = "R-DEFAULT"
    rationale["why"] = RULE_EXPLANATIONS["R-DEFAULT"]
    return Classification(RecoveryClass.MANUAL_REVIEW, "R-DEFAULT",
                          "deterministic", rationale)
