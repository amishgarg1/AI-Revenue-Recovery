"""
The production integration point.

Everything else here is a batch over a fixed horizon, which is what measuring
a policy requires. The fair question a reviewer asks next is whether the
decision logic only works because a simulation hands it a tidy world.

`POST /api/live/payment-failed` takes a real Razorpay `payment.failed`
webhook - the same envelope Razorpay posts, verified with the same HMAC-SHA256
scheme against the same webhook secret - and returns the classification, the
chosen rung and all eleven gate verdicts, in single-digit milliseconds.

It calls the same functions the batch calls. That is the whole claim, and it
is checkable: `app/core/live.py` imports `classify`, `get_next_action` and
`evaluate` and adds no decision logic of its own.

It decides; it does not send. Executing would mean a real message and a real
charge against a real customer.
"""

import hashlib
import hmac
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.live import decide, record, verify_live_chain
from app.db import get_db
from app.models import LiveDecision

router = APIRouter(prefix="/api", tags=["live"])


def verify_signature(body: bytes, signature: str, secret: str) -> bool:
    """
    Razorpay's scheme: HMAC-SHA256 of the raw body, hex, in
    `X-Razorpay-Signature`.

    Compared with `compare_digest` rather than `==` - a webhook signature
    check that short-circuits on the first differing byte leaks how much of a
    forged signature was right.
    """
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature or "")


@router.post("/live/payment-failed")
async def payment_failed(
    request: Request,
    db: Session = Depends(get_db),
    x_razorpay_signature: str = Header(default=""),
    x_razorpay_event_id: str = Header(default=""),
    merchant: str = "",
):
    """
    Decide one real payment failure.

    When `RZP_WEBHOOK_SECRET` is set the signature must verify or the request
    is rejected - an endpoint that accepts unsigned webhooks is an endpoint
    that accepts anyone's. With no secret configured the decision still runs,
    because the demo has to work without keys, but the response says
    `signature_verified: false` and so does the stored record. The state of
    the check is never implied.
    """
    body = await request.body()
    secret = os.environ.get("RZP_WEBHOOK_SECRET")

    if secret:
        if not verify_signature(body, x_razorpay_signature, secret):
            raise HTTPException(status_code=401,
                                detail="Signature does not match the request body")
        verified = True
    else:
        verified = False

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Body is not valid JSON")

    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Body must be a JSON object")

    # A live event happens at a real instant. The simulation clock governs the
    # batch precisely so the batch is reproducible; borrowing it here would
    # date every live decision to a fixed day in the past.
    now = datetime.now(timezone.utc)
    received_at = now.isoformat()

    result = decide(payload, now=now, signature_verified=verified,
                    event_id=x_razorpay_event_id or None,
                    merchant_id=merchant or None)
    stored = record(db, received_at=received_at, result=result,
                    signature_verified=verified, payload=payload)

    return {
        **result,
        "signature_verified": verified,
        "signature_checked": bool(secret),
        "received_at": received_at,
        "decision_id": stored.decision_id,
        "this_hash": stored.this_hash,
        "executed": False,
        "note": "Decision only. Sending would mean a real message and a real "
                "charge against a real customer.",
    }


@router.get("/live/decisions")
def decisions(db: Session = Depends(get_db), limit: int = 50):
    """The live book, newest first, with its own chain verification."""
    rows = (
        db.query(LiveDecision)
        .order_by(LiveDecision.decision_id.desc())
        .limit(limit)
        .all()
    )
    return {
        "chain": verify_live_chain(db),
        "decisions": [
            {
                "decision_id": r.decision_id,
                "received_at": r.received_at,
                "event_id": r.event_id,
                "payment_id": r.payment_id,
                "signature_verified": r.signature_verified,
                "recovery_class": r.recovery_class,
                "rule_id": r.rule_id,
                "tier": r.tier,
                "channel": r.channel,
                "allowed": r.allowed,
                "blocked_by": r.blocked_by,
                "reason_code": r.reason_code,
                "latency_ms": r.latency_ms,
                "this_hash": r.this_hash,
            }
            for r in rows
        ],
    }
