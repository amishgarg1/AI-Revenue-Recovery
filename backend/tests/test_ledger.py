"""
The audit ledger is only worth having if it detects tampering, so these tests
tamper with it.
"""

from app.core.ledger import GENESIS, append, verify_chain
from app.models import Event


def _append(db, **overrides):
    payload = {
        "ts": "2026-09-01T10:00:00+00:00",
        "tick": 0,
        "entity_type": "case",
        "entity_id": "case_0001",
        "actor": "classifier",
        "action": "CLASSIFY",
        "decision": "RETRY_TIMED",
        "reason_code": "R-05",
        "payload": {"amount_paise": 149900},
    }
    payload.update(overrides)
    return append(db, **payload)


def test_single_event_chains_from_genesis(db):
    _append(db)
    db.commit()

    event = db.query(Event).one()
    assert event.prev_hash == GENESIS

    result = verify_chain(db)
    assert result["valid"]
    assert result["records"] == 1


def test_chain_survives_a_roundtrip_through_the_database(db):
    """
    Regression test for the bug that made the ledger useless.

    The hash was computed over a timezone-aware timestamp but stored in a
    SQLite DateTime column, which comes back naive. Verification re-serialised
    a different string and every row failed, so the chain reported tampering
    that had not happened. Timestamps are now stored as the exact string that
    was hashed.
    """
    for i in range(25):
        _append(db, ts=f"2026-09-01T{i % 24:02d}:30:00+00:00", tick=i)
    db.commit()

    result = verify_chain(db)
    assert result["valid"], f"chain broke at {result['broken_at']}"
    assert result["broken_count"] == 0


def test_editing_a_payload_is_caught_and_pinpointed(db):
    """
    Verification walks forward from each row's *stored* hash, so an edited row
    is reported on its own rather than dragging every later row into the
    report. Naming one row is more useful than naming four hundred: it says
    exactly which decision was rewritten.
    """
    for i in range(5):
        _append(db, tick=i)
    db.commit()

    victim = db.query(Event).filter(Event.event_id == 2).one()
    victim.payload_json = {"amount_paise": 1}
    db.commit()

    result = verify_chain(db)
    assert not result["valid"]
    assert result["first_break"] == 2
    assert result["broken_at"] == [2]


def test_deleting_a_row_is_detected(db):
    for i in range(4):
        _append(db, tick=i)
    db.commit()

    db.delete(db.query(Event).filter(Event.event_id == 2).one())
    db.commit()

    assert not verify_chain(db)["valid"]


def test_reordering_is_detected(db):
    _append(db, decision="AUTO_RETRY", tick=0)
    _append(db, decision="NUDGE_CUSTOMER", tick=1)
    db.commit()

    first, second = db.query(Event).order_by(Event.event_id).all()
    first.decision, second.decision = second.decision, first.decision
    db.commit()

    assert not verify_chain(db)["valid"]


def test_empty_ledger_is_valid(db):
    result = verify_chain(db)
    assert result["valid"]
    assert result["records"] == 0
