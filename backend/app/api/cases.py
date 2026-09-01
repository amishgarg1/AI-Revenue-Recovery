"""Case list and the full decision timeline for one case."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Action, Case, Customer, Event, Invoice, Order, Payment

router = APIRouter(prefix="/api", tags=["cases"])


def _row(obj) -> dict:
    return {c.name: getattr(obj, c.name) for c in obj.__table__.columns}


@router.get("/cases")
def list_cases(
    db: Session = Depends(get_db),
    state: Optional[str] = None,
    arm: Optional[str] = None,
    recovery_class: Optional[str] = None,
    blocked_by: Optional[str] = None,
    limit: int = Query(50, le=500),
    offset: int = 0,
):
    query = db.query(Case)
    if state:
        query = query.filter(Case.state == state)
    if arm:
        query = query.filter(Case.arm == arm)
    if recovery_class:
        query = query.filter(Case.recovery_class == recovery_class)
    if blocked_by:
        blocked_ids = [
            a.case_id for a in db.query(Action.case_id)
            .filter(Action.blocked_by == blocked_by).distinct()
        ]
        query = query.filter(Case.case_id.in_(blocked_ids))

    total = query.count()
    rows = (
        query.order_by(Case.amount_at_risk_paise.desc())
        .offset(offset).limit(limit).all()
    )
    return {"total": total, "limit": limit, "offset": offset,
            "cases": [_row(c) for c in rows]}


@router.get("/cases/{case_id}")
def case_detail(case_id: str, db: Session = Depends(get_db)):
    """
    Everything about one case: the entity, the customer, every failed payment,
    every action with its full gate trail, and the raw ledger events.

    This is the view that answers "why did the system do that?" without anyone
    having to trust a summary.
    """
    case = db.query(Case).filter(Case.case_id == case_id).first()
    if not case:
        raise HTTPException(status_code=404, detail=f"No case {case_id}")

    entity = (
        db.query(Order).filter(Order.order_id == case.entity_id).first()
        if case.entity_type == "order"
        else db.query(Invoice).filter(Invoice.invoice_id == case.entity_id).first()
    )
    customer = (
        db.query(Customer).filter(Customer.customer_id == case.customer_id).first()
    )
    payments = (
        db.query(Payment).filter(Payment.order_id == case.entity_id)
        .order_by(Payment.attempt_no).all()
        if case.entity_type == "order" else []
    )
    actions = (
        db.query(Action).filter(Action.case_id == case_id)
        .order_by(Action.tick, Action.action_id).all()
    )
    events = (
        db.query(Event).filter(Event.entity_id == case_id)
        .order_by(Event.event_id).all()
    )

    return {
        "case": _row(case),
        "entity": _row(entity) if entity else None,
        "customer": _row(customer) if customer else None,
        "payments": [_row(p) for p in payments],
        "actions": [_row(a) for a in actions],
        "events": [_row(e) for e in events],
    }
