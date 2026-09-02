"""Read-only endpoints backing the dashboard."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.analytics.experiment import (
    calculate_experiment_results, exception_report, per_class_breakdown,
)
from app.analytics.report import delivery_report, full_report, guardrail_report
from app.analytics.sensitivity import sensitivity_report
from app.core import clock
from app.core.detector import detector
from app.db import get_db
from app.models import Case, Payment

router = APIRouter(prefix="/api", tags=["metrics"])


def _cases(db: Session):
    return [
        {c.name: getattr(case, c.name) for c in case.__table__.columns}
        for case in db.query(Case)
    ]


@router.get("/metrics/summary")
def summary(db: Session = Depends(get_db)):
    """The command-centre numbers."""
    return calculate_experiment_results(_cases(db), guardrail_report(db))


@router.get("/metrics/experiment")
def experiment(db: Session = Depends(get_db)):
    cases = _cases(db)
    return {
        "overall": calculate_experiment_results(cases),
        "per_class": per_class_breakdown(cases),
    }


@router.get("/metrics/guardrails")
def guardrails(db: Session = Depends(get_db)):
    return guardrail_report(db)


@router.get("/metrics/delivery")
def delivery(db: Session = Depends(get_db)):
    return delivery_report(db)


@router.get("/metrics/exceptions")
def exceptions(db: Session = Depends(get_db)):
    """Everything not recovered, grouped by why. Part of the result."""
    return {"exceptions": exception_report(_cases(db))}


@router.get("/metrics/issuer-health")
def issuer_health(db: Session = Depends(get_db)):
    if not detector.health_report():
        detector.load_payments(
            [{c.name: getattr(p, c.name) for c in p.__table__.columns}
             for p in db.query(Payment)]
        )
    return {
        "at": clock.iso(clock.BATCH_START),
        "issuers": detector.health_report(at=clock.BATCH_START),
    }


@router.get("/metrics/full")
def full(db: Session = Depends(get_db)):
    """Everything at once — the exact payload `make report` renders."""
    return full_report(db)


@router.get("/metrics/funnel")
def funnel(db: Session = Depends(get_db), arm: str = Query("treatment")):
    """Cases by state and by recovery class, for the dashboard funnel."""
    from collections import Counter

    cases = [c for c in db.query(Case) if c.arm == arm]
    return {
        "arm": arm,
        "total": len(cases),
        "by_state": dict(Counter(c.state for c in cases)),
        "by_class": dict(Counter(c.recovery_class for c in cases)),
        "by_touches": dict(Counter(c.touches_used for c in cases)),
    }


@router.get("/metrics/sensitivity")
def sensitivity(db: Session = Depends(get_db)):
    """
    How far the chosen assumptions can be wrong before the conclusion changes.

    Every parameter in the outcome oracle is moved across a wide range and the
    experiment recomputed. This is a recomputation rather than a re-run,
    because no decision module reads the oracle - the actions taken are fixed,
    only whether the customer paid is re-decided.
    """
    return sensitivity_report(db)
