"""
What a person is allowed to do to a case, and the record of them doing it.

Every action here ends up in the same hash-chained ledger as the agent's own
decisions, with the operator named and a reason they had to type. That is the
point: a queue where a human can quietly override a guardrail is worse than no
queue, because the audit trail then describes a system that was not the one
running.

The rule that matters most
--------------------------
**An operator cannot touch a control-arm case.** Not "should not" - the call
raises. The control arm is 163 cases the agent was never allowed to contact,
and the entire measured lift is the difference against them. One well-meaning
operator working the queue would destroy the experiment silently, and it would
be indistinguishable afterwards from the policy having worked.

There is a test for it, and it is the first test in the file.

Why a reason is mandatory
-------------------------
An override with no reason is an override nobody can review. `WRITE_OFF` on a
case a compliance officer asks about six months later has to answer "why", and
"an operator clicked it" is not an answer. Empty and whitespace-only reasons
are refused.

What is deliberately not here
-----------------------------
Sending. `APPROVE_CONTACT` records that a person judged an automated refusal
wrong; it does not then dispatch a message. Executing means a real charge
against a real customer, and the same line is drawn in the live webhook path.
"""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.core.ledger import append
from app.models import Case

# What an operator may record, and what it means for the case.
#
# The state each action lands the case in is declared here rather than decided
# inside the function, so the whole set can be read at once - a reviewer asking
# "what can a human do to a case" gets one table rather than four branches.
ACTIONS = {
    "APPROVE_CONTACT": {
        "state": None,             # judgement recorded; the case stays open
        "resolution": None,
        "describes": "A person judged an automated refusal wrong. Recorded, "
                     "not executed.",
    },
    "WRITE_OFF": {
        "state": "CLOSED",
        "resolution": "WRITTEN_OFF_BY_OPERATOR",
        "describes": "Not worth pursuing further. Stops all spend on the case.",
    },
    "MARK_PAID_OFFLINE": {
        "state": "RECOVERED",
        "resolution": "PAID_OFFLINE",
        "describes": "Settled through a route the system cannot see - a bank "
                     "transfer, a cheque, a phone payment.",
    },
    "HOLD": {
        "state": None,
        "resolution": None,
        "describes": "Park the case pending something outside the system. No "
                     "further automated contact until released.",
    },
}


class OperatorError(ValueError):
    """An action that must not be recorded. Never swallowed into a no-op."""


def _require_reason(reason: Optional[str]) -> str:
    text = (reason or "").strip()
    if len(text) < 3:
        raise OperatorError(
            "A reason is required. An override nobody can review is worse "
            "than no override - a compliance question six months from now has "
            "to be answerable with more than 'an operator clicked it'.")
    return text


def act(db: Session, *, case_id: str, action: str, operator: str,
        reason: str) -> dict:
    """
    Record one operator action against one case.

    Appends to the ledger before returning, so a caller cannot act and fail to
    log. The ledger entry is the deliverable; the state change is a
    consequence of it.
    """
    if action not in ACTIONS:
        raise OperatorError(
            f"Unknown action {action!r}. Valid actions: {sorted(ACTIONS)}")

    if not (operator or "").strip():
        raise OperatorError("An operator id is required; actions are attributed")

    text = _require_reason(reason)

    case = db.query(Case).filter(Case.case_id == case_id).first()
    if case is None:
        raise OperatorError(f"No such case: {case_id}")

    # The guard. Stated as an error rather than a filter, because a queue that
    # merely hides control cases still lets a direct call through.
    if case.arm == "control":
        raise OperatorError(
            f"{case_id} is in the control arm and must never be worked. The "
            "measured lift is the difference against these cases; touching "
            "one destroys the experiment, and afterwards it is "
            "indistinguishable from the policy having worked.")

    if case.state in ("RECOVERED", "CLOSED") and action != "APPROVE_CONTACT":
        raise OperatorError(
            f"{case_id} is already {case.state}. Re-closing a closed case "
            "would put two contradictory outcomes in its trail.")

    spec = ACTIONS[action]
    before = {"state": case.state, "resolution": case.resolution}

    if spec["state"]:
        case.state = spec["state"]
        case.resolution = spec["resolution"]
        if spec["state"] == "RECOVERED":
            # Recorded as recovered, but not as money the agent recovered: the
            # customer paid through a route the system never touched, and
            # crediting it to the policy would inflate the lift.
            case.recovered_paise = case.amount_at_risk_paise
            case.exception_reason = None
        else:
            case.exception_reason = text

    # `ts` is real wall-clock here. The simulation clock governs the batch so
    # the batch stays reproducible; an operator acts at an actual moment, and
    # dating their decision to a fixed day in the past would make the trail
    # useless to the person reviewing it.
    now = datetime.now(timezone.utc).isoformat()

    this_hash = append(
        db,
        ts=now,
        tick=None,
        entity_type="case",
        entity_id=case.case_id,
        actor=f"operator:{operator.strip()}",
        action=f"OPERATOR_{action}",
        decision=action,
        reason_code=action,
        payload={
            "reason": text,
            "before": before,
            "after": {"state": case.state, "resolution": case.resolution},
            "amount_at_risk_paise": case.amount_at_risk_paise,
            "describes": spec["describes"],
            # Whether the money should be attributed to the policy. Only the
            # batch's own outcomes count towards the measured lift.
            "counts_towards_lift": False,
        },
        commit=True,
    )

    return {
        "case_id": case.case_id,
        "action": action,
        "operator": operator.strip(),
        "reason": text,
        "state": case.state,
        "resolution": case.resolution,
        "recorded_at": now,
        "ledger_hash": this_hash,
        "executed": False,
        "note": spec["describes"],
    }
