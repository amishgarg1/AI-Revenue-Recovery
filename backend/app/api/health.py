"""Liveness and configuration transparency."""

import os

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.analytics.report import GATE_NAMES
from app.core import clock
from app.core.classifier import RecoveryClass
from app.db import get_db
from app.models import Action, Case, Event

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
def health(db: Session = Depends(get_db)):
    """
    Also reports which optional integrations are configured.

    The demo runs with no keys at all, so a viewer should be able to tell at a
    glance whether the payment links and message bodies they are looking at
    came from live services or from the deterministic fallbacks — rather than
    having to take the README's word for it.
    """
    return {
        "status": "ok",
        "simulation": {
            "batch_start": clock.iso(clock.BATCH_START),
            "batch_end": clock.iso(clock.BATCH_END),
            "ticks": clock.TICK_COUNT,
            "tick_hours": clock.TICK_HOURS,
        },
        # The two enumerations the dashboard filters on. They are served rather
        # than duplicated in the frontend because a hardcoded copy is a copy
        # that goes stale: two recovery classes were added mid-build and the
        # filter kept offering the old nine, so the new ones were unreachable
        # from the UI while being perfectly present in the data.
        "catalog": {
            "recovery_classes": [c.value for c in RecoveryClass],
            "gates": sorted(GATE_NAMES),
        },
        "data": {
            "cases": db.query(Case).count(),
            "actions": db.query(Action).count(),
            "events": db.query(Event).count(),
        },
        "integrations": {
            "razorpay_test_mode": bool(
                os.environ.get("RZP_KEY_ID") and os.environ.get("RZP_KEY_SECRET")
            ),
            "llm": bool(os.environ.get("GROQ_API_KEY") or os.environ.get("GEMINI_API_KEY")),
            "voice_tts": bool(os.environ.get("SARVAM_API_KEY")),
        },
    }


@router.get("/policy")
def policy():
    """
    The rules in force, and whose they are.

    A guardrail nobody can inspect is a guardrail nobody can audit. This serves
    the resolved policy for every configured merchant, so a reviewer can see
    what each one's gates will actually enforce rather than reading the code.
    """
    from dataclasses import asdict

    from app.core import config

    book = config.book()

    def described(p):
        row = asdict(p)
        # Rung prices come back with integer keys; JSON needs strings, and a
        # reader wants rupees rather than paise.
        row["tier_cost_rupees"] = {
            str(t): c / 100 for t, c in p.tier_cost_paise.items()
        }
        return row

    return {
        # None when no file is present, which is a supported way to run.
        "source": book.source,
        "defaults": described(book.default),
        "merchants": {
            merchant_id: described(p) for merchant_id, p in book.merchants.items()
        },
    }
