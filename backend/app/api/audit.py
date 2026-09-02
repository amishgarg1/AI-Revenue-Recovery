"""
Audit ledger endpoints, including the one that deliberately breaks it.

`/api/audit/tamper` exists so the integrity claim can be demonstrated rather
than asserted: verify the chain (valid), rewrite one historical amount, verify
again (invalid, and it names the row). An audit trail nobody has seen fail is
just a log table.

`/api/audit/restore` puts the row back. Without it the demonstration is a
one-way door: the ledger reads BROKEN on every page from then on, and the
committed database has to be restored from git. It also proves the point the
tamper alone cannot — that detection is derived from the content and not from
some "edited" flag, because putting the original bytes back makes the chain
verify again.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.ledger import verify_chain
from app.db import get_db
from app.models import Event

router = APIRouter(prefix="/api", tags=["audit"])

# What each tampered row held before it was tampered with, so restore can put
# exactly that back. Kept in the process rather than accepted from the caller:
# an endpoint that writes caller-supplied content into an audit ledger is the
# opposite of the thing being demonstrated.
#
# If the process restarts while a row is still tampered, the committed
# database is the fallback — `git checkout backend/demo.db`.
_pre_tamper: dict = {}


@router.get("/audit/verify")
def verify(db: Session = Depends(get_db)):
    return verify_chain(db)


@router.get("/audit/events")
def events(
    db: Session = Depends(get_db),
    entity_id: Optional[str] = None,
    actor: Optional[str] = None,
    action: Optional[str] = None,
    limit: int = Query(100, le=1000),
    offset: int = 0,
):
    query = db.query(Event)
    if entity_id:
        query = query.filter(Event.entity_id == entity_id)
    if actor:
        query = query.filter(Event.actor == actor)
    if action:
        query = query.filter(Event.action == action)

    total = query.count()
    rows = query.order_by(Event.event_id).offset(offset).limit(limit).all()
    return {
        "total": total,
        "events": [
            {c.name: getattr(e, c.name) for c in e.__table__.columns} for e in rows
        ],
    }


@router.post("/audit/tamper")
def tamper(db: Session = Depends(get_db), event_id: Optional[int] = None):
    """
    Rewrite one recorded amount, the way someone covering their tracks would.

    Nothing else is touched — the row keeps its stored hash, which is exactly
    why the next verification catches it.
    """
    query = db.query(Event).filter(Event.action == "OUTCOME")
    event = (
        db.query(Event).filter(Event.event_id == event_id).first()
        if event_id else query.first() or db.query(Event).first()
    )
    if not event:
        raise HTTPException(status_code=400, detail="No events to tamper with")

    before = dict(event.payload_json or {})
    after = dict(before)
    after["amount_paise"] = 9_99_99_999
    event.payload_json = after
    db.commit()

    # Remember the original only the first time, so tampering twice in a row
    # cannot overwrite it with the already-tampered payload.
    _pre_tamper.setdefault(event.event_id, before)

    return {
        "status": "tampered",
        "event_id": event.event_id,
        "before": before,
        "after": after,
        "hint": "GET /api/audit/verify now reports valid=false and names this row",
    }


@router.post("/audit/restore")
def restore(db: Session = Depends(get_db)):
    """
    Put every tampered row back, and the chain verifies again.

    Restoring is what makes the demonstration repeatable, and it is also the
    stronger half of the claim: the same bytes produce the same hash, so the
    chain does not need to be told an edit was undone.
    """
    if not _pre_tamper:
        return {"status": "nothing_to_restore", "restored": [],
                "chain": verify_chain(db)}

    restored = []
    for event_id, payload in list(_pre_tamper.items()):
        event = db.query(Event).filter(Event.event_id == event_id).first()
        if event is None:
            continue
        event.payload_json = payload
        restored.append(event_id)
    db.commit()
    _pre_tamper.clear()

    return {"status": "restored", "restored": restored,
            "chain": verify_chain(db)}
