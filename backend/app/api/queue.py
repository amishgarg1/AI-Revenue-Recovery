"""
The human-review queue, and the actions a person can take on it.

Tier 4 is 89% of total spend and had nowhere to go: cases were routed to a
person, billed for their attention, and then left. These endpoints are the
missing half - the queue itself, its economics, and a way to work it that
lands in the same audit trail as everything the agent did.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core import queue as review
from app.core.operator import ACTIONS, OperatorError, act
from app.db import get_db

router = APIRouter(prefix="/api", tags=["queue"])


class ActionIn(BaseModel):
    action: str
    operator: str
    reason: str


@router.get("/queue")
def get_queue(
    db: Session = Depends(get_db),
    limit: int = Query(100, le=500),
    include_worked: bool = False,
):
    """
    Cases waiting on a person, most money first, with the lane's economics.

    The economics come back alongside the rows rather than on a separate call,
    because the queue is not readable without them: thirty-four cases is a
    short list, and whether working it is worth anything is the only
    interesting question about it.
    """
    return {
        "queue": review.queue(db, limit=limit, include_worked=include_worked),
        "economics": review.economics(db),
        "actions": [
            {"action": name, "describes": spec["describes"],
             "closes_case": bool(spec["state"])}
            for name, spec in ACTIONS.items()
        ],
    }


@router.post("/queue/{case_id}/act")
def take_action(case_id: str, body: ActionIn, db: Session = Depends(get_db)):
    """
    Record an operator action against one case.

    Refused with a 422 rather than silently ignored when the action cannot be
    recorded: an unknown action, a missing reason, a case already closed, or a
    control-arm case. That last one is the important refusal - see
    `app/core/operator.py`.
    """
    try:
        return act(db, case_id=case_id, action=body.action,
                   operator=body.operator, reason=body.reason)
    except OperatorError as e:
        raise HTTPException(status_code=422, detail=str(e))
