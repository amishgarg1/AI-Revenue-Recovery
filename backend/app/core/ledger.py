"""
Append-only, hash-chained audit ledger.

Every decision the system makes lands here: the classifier rule that fired,
each of the eleven gate verdicts, every LLM call and its validation result,
every send, every outcome. A case's whole life can be reconstructed from these
rows alone.

Each row's hash covers the previous row's hash plus its own canonical JSON, so
editing any historical row invalidates every hash after it. `verify_chain`
reports exactly where the break is.

Design note — the timestamp
---------------------------
`ts` is stored as the same ISO-8601 string that went into the hash. The
earlier version hashed a timezone-aware `isoformat()` but stored a SQLAlchemy
`DateTime`, which SQLite hands back naive. Verification then re-serialised a
*different* string and every single row failed. The chain was reporting
tampering that had not happened, which is worse than useless — it trains you to
ignore the alarm. Hash the bytes you store.
"""

import hashlib
import json
from typing import Optional

from sqlalchemy.orm import Session

from app.models import Event

GENESIS = "0" * 64

# The chain head, cached in-process. A batch writes thousands of events, and
# re-reading the tail row before each one turns the ledger into the slowest part
# of the system. The cache is only ever advanced by our own appends; anything
# that touches the table behind our back (a fresh database, the tamper demo)
# calls reset_head_cache().
_head_cache: Optional[str] = None


def reset_head_cache():
    global _head_cache
    _head_cache = None

# Fields covered by the hash, in the order they are written. Changing this list
# changes every hash, so it is deliberately explicit rather than derived from
# the model.
HASHED_FIELDS = (
    "ts", "tick", "entity_type", "entity_id",
    "actor", "action", "decision", "reason_code", "payload",
)


def canonical(d: dict) -> str:
    """Stable JSON: sorted keys, no incidental whitespace."""
    return json.dumps(d, sort_keys=True, separators=(",", ":"), default=str)


def _row_digest(prev_hash: str, row: dict) -> str:
    ordered = {k: row.get(k) for k in HASHED_FIELDS}
    return hashlib.sha256((prev_hash + canonical(ordered)).encode()).hexdigest()


def append(db: Session, *, ts: str, entity_type: str, entity_id: str, actor: str,
           action: str, decision: str, reason_code: str, payload: dict,
           tick: Optional[int] = None, commit: bool = False) -> str:
    """
    Append one event and return its hash.

    `ts` is passed in rather than read from the wall clock so the ledger stays
    on the simulation clock like everything else — the audit trail has to be
    reproducible too, or the demo is not reproducible.

    `commit` defaults to False: the caller commits once per case, so a case is
    written atomically instead of leaving a half-written trail if something
    fails mid-way.
    """
    global _head_cache

    if _head_cache is None:
        prev = (
            db.query(Event.this_hash)
            .order_by(Event.event_id.desc())
            .limit(1)
            .scalar()
        )
        _head_cache = prev if prev else GENESIS
    prev_hash = _head_cache

    row = {
        "ts": ts,
        "tick": tick,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "actor": actor,
        "action": action,
        "decision": decision,
        "reason_code": reason_code,
        "payload": payload,
    }
    this_hash = _row_digest(prev_hash, row)

    db.add(Event(
        ts=ts,
        tick=tick,
        entity_type=entity_type,
        entity_id=entity_id,
        actor=actor,
        action=action,
        decision=decision,
        reason_code=reason_code,
        payload_json=payload,
        prev_hash=prev_hash,
        this_hash=this_hash,
    ))
    _head_cache = this_hash
    if commit:
        db.commit()
    return this_hash


def verify_chain(db: Session) -> dict:
    """
    Recompute every hash from genesis and report the first divergence.

    `broken_at` lists the event_ids whose stored hash does not match a fresh
    computation over their own content. Each row is checked against the
    *stored* hash of its predecessor rather than the recomputed one, so an
    edited row is named on its own instead of dragging every subsequent row
    into the report. Pointing at one rewritten decision is more useful than
    reporting that four hundred rows "look wrong".
    """
    prev_hash = GENESIS
    bad = []
    total = 0

    for e in db.query(Event).order_by(Event.event_id).yield_per(500):
        total += 1
        row = {
            "ts": e.ts,
            "tick": e.tick,
            "entity_type": e.entity_type,
            "entity_id": e.entity_id,
            "actor": e.actor,
            "action": e.action,
            "decision": e.decision,
            "reason_code": e.reason_code,
            "payload": e.payload_json,
        }
        expect = _row_digest(prev_hash, row)
        if expect != e.this_hash:
            bad.append(e.event_id)
        # Continue from the *stored* hash so one bad row does not silently
        # re-align the rest of the chain.
        prev_hash = e.this_hash

    return {
        "valid": len(bad) == 0,
        "records": total,
        "broken_at": bad[:50],
        "broken_count": len(bad),
        "first_break": bad[0] if bad else None,
    }
