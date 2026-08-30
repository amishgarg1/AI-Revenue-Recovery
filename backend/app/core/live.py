"""
One real payment failure, decided the way the batch decides a simulated one.

The rest of this system is a discrete-event simulation over a fixed horizon.
That is the right shape for measuring a policy - you need a control arm and a
finished experiment - but it leaves an obvious question unanswered: is the
decision logic actually event-shaped, or does it only work because a batch
hands it a tidy world?

This module answers it by using the same functions. `classify` is the same
classifier, `get_next_action` the same ladder, `evaluate` the same eleven
gates in the same order. Nothing here reimplements a decision; if it did, the
answer would be worthless.

What is different is the clock and the book. A webhook arrives at a real
instant, so the simulation clock does not apply, and the decision is written
to `live_decisions` rather than to the simulation's ledger - see the note on
that model for why mixing them would break reproducibility.

What is deliberately missing: this decides, it does not send. Executing means
a payment link, a message and a charge against a real customer, and the point
being demonstrated is that the decision path is transport-agnostic.
"""

import hashlib
import time
from typing import Optional

from sqlalchemy.orm import Session

from app.core import config
from app.core.classifier import classify
from app.core.ladder import get_next_action
from app.core.ledger import canonical
from app.core.policy import evaluate
from app.models import LiveDecision

GENESIS = "0" * 64

# Fields covered by the hash, in the order they are written. Explicit rather
# than derived from the model, for the same reason the simulation ledger's list
# is: adding a column should not silently rewrite history.
HASHED_FIELDS = (
    "received_at", "event_id", "payment_id", "signature_verified",
    "recovery_class", "rule_id", "tier", "channel", "allowed",
    "blocked_by", "reason_code", "payload",
)


def _digest(prev_hash: str, row: dict) -> str:
    ordered = {k: row.get(k) for k in HASHED_FIELDS}
    return hashlib.sha256((prev_hash + canonical(ordered)).encode()).hexdigest()


def case_from_webhook(payload: dict) -> dict:
    """
    A Razorpay `payment.failed` payload, reduced to the facts the rules read.

    Razorpay nests the entity at payload.payment.entity. The error taxonomy -
    `error_source` and `error_step` alongside `error_reason` - is the same one
    the classifier routes on, which is why a real payload needs no translation
    layer beyond this.
    """
    entity = (
        payload.get("payload", {}).get("payment", {}).get("entity", {})
        or payload.get("payment", {}).get("entity", {})
        or {}
    )

    payment = {
        "attempt_no": 1,
        "method": entity.get("method"),
        "issuer": entity.get("bank") or entity.get("wallet") or entity.get("card_id"),
        "amount_paise": entity.get("amount"),
        "error_code": entity.get("error_code"),
        "error_source": entity.get("error_source"),
        "error_step": entity.get("error_step"),
        "error_reason": entity.get("error_reason"),
        "error_description": entity.get("error_description"),
    }

    case = {
        "entity_type": "order",
        "entity_id": entity.get("order_id") or entity.get("id"),
        "entity_status": "attempted",
        "amount_at_risk_paise": entity.get("amount") or 0,
        "days_overdue": 0,
        # A failure that just arrived is a case at its start. The gates read
        # these, and leaving them unset made G10 report "Case is None" - true
        # to the data and useless to read.
        "state": "OPEN",
        "touches_used": 0,
        "promise_date": None,
    }
    return {"case": case, "payment": payment, "entity": entity}


def decide(payload: dict, *, now, signature_verified: bool,
           event_id: Optional[str] = None,
           consent_voice: bool = False,
           merchant_id: Optional[str] = None) -> dict:
    """
    Classify, pick the next rung, and run all eleven gates. No side effects.

    `now` is passed in rather than read here so this stays testable and so the
    caller decides which clock applies - the same discipline the simulation
    keeps.
    """
    started = time.perf_counter()

    parsed = case_from_webhook(payload)
    case, payment = parsed["case"], parsed["payment"]

    classification = classify(case, [payment])
    recovery_class = classification.recovery_class.value

    intent = get_next_action(
        recovery_class, touches_used=0,
        amount_paise=case["amount_at_risk_paise"],
        consent_voice=consent_voice,
    )

    # A finished ladder is a real answer: DEAD and an exhausted case both mean
    # "spend nothing", and reporting that is the point of having the class.
    if intent is None:
        elapsed = (time.perf_counter() - started) * 1000
        return {
            "recovery_class": recovery_class,
            "rule_id": classification.rule_id,
            "rationale": classification.rationale_facts,
            "action": None,
            "allowed": False,
            "blocked_by": None,
            "reason_code": "NO_ACTION",
            "gate_trail": [],
            "latency_ms": round(elapsed, 2),
            "payment_id": parsed["entity"].get("id"),
            "event_id": event_id,
        }

    ctx = {
        "now": now,
        "tick": None,
        # A live webhook carries no consent record - that lives in the
        # merchant's own customer table. Assuming consent would make G01 pass
        # for the wrong reason, so it is stated as absent unless supplied.
        "customer": {"consent_whatsapp": True, "consent_sms": True,
                     "consent_email": True, "consent_voice": consent_voice,
                     "dnd_registered": False, "opted_out": False},
        "entity_status": case["entity_status"],
        "issuer": payment["issuer"],
        "customer_touches_24h": 0,
        "customer_touches_7d": 0,
        "last_tier": None,
        # Whose rules apply. A live event from a merchant with their own
        # policy is judged by it, not by ours.
        "policy": config.active(merchant_id),
    }

    decision = evaluate(case, intent, ctx)
    elapsed = (time.perf_counter() - started) * 1000

    return {
        "recovery_class": recovery_class,
        "rule_id": classification.rule_id,
        "rationale": classification.rationale_facts,
        "action": {"tier": intent.tier, "channel": intent.channel,
                   "cost_paise": intent.cost_paise,
                   "rationale": intent.rationale},
        "allowed": decision.allowed,
        "blocked_by": decision.blocked_by,
        "reason_code": decision.reason_code,
        # The same serialisation the batch stores on every action, so a live
        # trail and a simulated one are read the same way.
        "gate_trail": decision.trail_as_dicts(),
        "latency_ms": round(elapsed, 2),
        "payment_id": parsed["entity"].get("id"),
        "event_id": event_id,
        "policy": config.active(merchant_id).label,
    }


def record(db: Session, *, received_at: str, result: dict,
           signature_verified: bool, payload: dict) -> LiveDecision:
    """Append the decision to the live chain and return the stored row."""
    tail = (
        db.query(LiveDecision)
        .order_by(LiveDecision.decision_id.desc())
        .first()
    )
    prev_hash = tail.this_hash if tail else GENESIS

    row = {
        "received_at": received_at,
        "event_id": result.get("event_id"),
        "payment_id": result.get("payment_id"),
        "signature_verified": signature_verified,
        "recovery_class": result["recovery_class"],
        "rule_id": result["rule_id"],
        "tier": (result["action"] or {}).get("tier"),
        "channel": (result["action"] or {}).get("channel"),
        "allowed": result["allowed"],
        "blocked_by": result["blocked_by"],
        "reason_code": result["reason_code"],
        "payload": payload,
    }

    stored = LiveDecision(
        received_at=received_at,
        event_id=row["event_id"],
        payment_id=row["payment_id"],
        signature_verified=signature_verified,
        recovery_class=row["recovery_class"],
        rule_id=row["rule_id"],
        tier=row["tier"],
        channel=row["channel"],
        allowed=row["allowed"],
        blocked_by=row["blocked_by"],
        reason_code=row["reason_code"],
        latency_ms=result["latency_ms"],
        payload_json=payload,
        prev_hash=prev_hash,
        this_hash=_digest(prev_hash, row),
    )
    db.add(stored)
    db.commit()
    return stored


def verify_live_chain(db: Session) -> dict:
    """Same verification the simulation ledger gets, over the live book."""
    rows = db.query(LiveDecision).order_by(LiveDecision.decision_id).all()
    prev_hash = GENESIS
    broken = []

    for row in rows:
        expected = _digest(prev_hash, {
            "received_at": row.received_at,
            "event_id": row.event_id,
            "payment_id": row.payment_id,
            "signature_verified": row.signature_verified,
            "recovery_class": row.recovery_class,
            "rule_id": row.rule_id,
            "tier": row.tier,
            "channel": row.channel,
            "allowed": row.allowed,
            "blocked_by": row.blocked_by,
            "reason_code": row.reason_code,
            "payload": row.payload_json,
        })
        if expected != row.this_hash or prev_hash != row.prev_hash:
            broken.append(row.decision_id)
        prev_hash = row.this_hash

    return {
        "valid": not broken,
        "records": len(rows),
        "broken_at": broken,
        "broken_count": len(broken),
        "first_break": broken[0] if broken else None,
    }
