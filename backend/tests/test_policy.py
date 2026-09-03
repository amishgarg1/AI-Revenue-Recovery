"""
Policy engine tests.

Each gate gets a case that must be blocked and, where the distinction matters,
a neighbouring case that must be allowed — a gate that blocks everything passes
a one-sided test and fails in production.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.core.clock import IST
from app.core.ladder import ActionIntent
from app.core import config
from app.core.policy import evaluate

CONSENTING = {
    "consent_whatsapp": True, "consent_sms": True,
    "consent_email": True, "consent_voice": True,
    "opted_out_at": None, "dnd_registered": False,
}


def at_ist(hour: int, day: int = 1) -> datetime:
    return datetime(2026, 9, day, hour, 0, tzinfo=IST).astimezone(timezone.utc)


def case(**overrides) -> dict:
    base = {
        "case_id": "case_0001",
        "state": "OPEN",
        "recovery_class": "NUDGE_CUSTOMER",
        "amount_at_risk_paise": 500_000,
        "touches_used": 0,
        "last_touch_at": None,
        "promise_date": None,
    }
    base.update(overrides)
    return base


def ctx(**overrides) -> dict:
    base = {
        "now": at_ist(11),
        "customer": dict(CONSENTING),
        "entity_status": "abandoned",
        "issuer": "HDFC",
        "customer_touches_24h": 0,
        "customer_touches_7d": 0,
        "last_tier": None,
    }
    base.update(overrides)
    return base


def whatsapp(cost=30) -> ActionIntent:
    return ActionIntent(tier=1, channel="whatsapp", cost_paise=cost, rationale="t")


def silent() -> ActionIntent:
    return ActionIntent(tier=0, channel="silent", cost_paise=0, rationale="t")


def voice() -> ActionIntent:
    return ActionIntent(tier=3, channel="voice", cost_paise=150, rationale="t")


def test_a_clean_case_is_allowed():
    decision = evaluate(case(), whatsapp(), ctx())
    assert decision.allowed, decision.blocked_by
    assert decision.blocked_by is None


def test_every_gate_is_evaluated_even_after_a_block():
    """
    The full trail is the deliverable. Stopping at the first refusal would make
    the case timeline show one verdict where a reviewer needs eleven.
    """
    decision = evaluate(case(), whatsapp(),
                        ctx(customer={**CONSENTING, "opted_out_at": "2026-08-01"}))
    assert not decision.allowed
    assert decision.blocked_by == "G01"
    assert len(decision.gate_trail) == 11
    assert [g.gate_id for g in decision.gate_trail] == [
        f"G{i:02d}" for i in range(1, 12)
    ]


# ------------------------------------------------------------------ G01 consent

def test_opted_out_customer_is_never_contacted():
    decision = evaluate(case(), whatsapp(),
                        ctx(customer={**CONSENTING, "opted_out_at": "2026-08-01"}))
    assert decision.blocked_by == "G01"
    assert decision.reason_code == "OPTED_OUT"
    assert decision.compliance_risk_avoided_paise > 0


def test_missing_channel_consent_blocks_only_that_channel():
    no_whatsapp = {**CONSENTING, "consent_whatsapp": False}
    assert evaluate(case(), whatsapp(), ctx(customer=no_whatsapp)).blocked_by == "G01"
    # A silent gateway retry reaches nobody, so channel consent cannot apply.
    assert evaluate(case(), silent(), ctx(customer=no_whatsapp, issuer=None)).allowed


def test_dnd_blocks_voice_but_not_messaging():
    dnd = {**CONSENTING, "dnd_registered": True}
    voice_case = case(touches_used=2)
    assert evaluate(voice_case, voice(),
                    ctx(customer=dnd, last_tier=2)).blocked_by == "G01"
    assert evaluate(case(), whatsapp(), ctx(customer=dnd)).allowed


# -------------------------------------------------------------- G02 quiet hours

@pytest.mark.parametrize("hour", [21, 23, 0, 4, 8])
def test_no_contact_at_night(hour):
    decision = evaluate(case(), whatsapp(), ctx(now=at_ist(hour)))
    assert decision.blocked_by == "G02"
    assert decision.reason_code == "QUIET_HOURS"


@pytest.mark.parametrize("hour", [9, 13, 20])
def test_contact_allowed_during_the_day(hour):
    assert evaluate(case(), whatsapp(), ctx(now=at_ist(hour))).allowed


def test_silent_retries_are_exempt_from_quiet_hours():
    """A gateway retry does not wake anybody up."""
    assert evaluate(case(recovery_class="AUTO_RETRY"), silent(),
                    ctx(now=at_ist(3), issuer=None)).allowed


def test_voice_has_a_narrower_window_than_messaging():
    late = ctx(now=at_ist(20), last_tier=2)
    voice_case = case(touches_used=2)
    assert evaluate(voice_case, voice(), late).reason_code == "VOICE_HOURS"
    assert evaluate(case(), whatsapp(), ctx(now=at_ist(20))).allowed


# ----------------------------------------------------------- G03 frequency cap

def test_one_touch_per_day_per_customer():
    assert evaluate(case(), whatsapp(), ctx(customer_touches_24h=1)).blocked_by == "G03"


def test_three_touches_per_week_per_customer():
    decision = evaluate(case(), whatsapp(),
                        ctx(customer_touches_24h=0, customer_touches_7d=3))
    assert decision.reason_code == "FREQ_CAP_7D"


def test_frequency_cap_counts_the_customer_not_the_case():
    """
    Two failed orders from one person is one person. Capping per case would let
    a customer with four open carts be messaged four times a day.
    """
    assert evaluate(case(case_id="a"), whatsapp(),
                    ctx(customer_touches_24h=1)).blocked_by == "G03"


# ------------------------------------------------------- G04 / G05 pacing rules

def test_attempt_budget_is_enforced_by_the_gate():
    assert evaluate(case(touches_used=3), whatsapp(), ctx()).blocked_by == "G04"


def test_cooldown_between_touches_on_one_case():
    recent = ctx()["now"] - timedelta(hours=2)
    decision = evaluate(case(last_touch_at=recent.isoformat()), whatsapp(), ctx())
    assert decision.blocked_by == "G05"


def test_cooldown_clears_after_six_hours():
    old = ctx()["now"] - timedelta(hours=7)
    assert evaluate(case(last_touch_at=old.isoformat()), whatsapp(), ctx()).allowed


# ------------------------------------------------------------ G06 amount band

def test_tiny_amounts_are_not_worth_chasing():
    decision = evaluate(case(amount_at_risk_paise=4_000), whatsapp(), ctx())
    assert decision.blocked_by == "G06"
    assert decision.reason_code == "BELOW_VIABLE_FLOOR"


def test_cost_may_not_exceed_the_share_cap():
    decision = evaluate(case(amount_at_risk_paise=config.active().min_viable_amount_paise + 100),
                        whatsapp(cost=5_000), ctx())
    assert decision.reason_code == "COST_EXCEEDS_BAND"


def test_free_actions_skip_the_amount_band():
    assert evaluate(case(amount_at_risk_paise=100, recovery_class="AUTO_RETRY"),
                    silent(), ctx(issuer=None)).allowed


# --------------------------------------------------- G07 / G09 / G10 hard stops

def test_risk_blocked_cases_are_never_auto_contacted():
    decision = evaluate(case(recovery_class="MANUAL_REVIEW"), whatsapp(), ctx())
    assert decision.blocked_by == "G07"


def test_risk_blocked_cases_may_still_reach_a_human():
    human = ActionIntent(tier=4, channel="human", cost_paise=5000, rationale="t")
    assert evaluate(case(recovery_class="MANUAL_REVIEW"), human, ctx()).allowed


def test_an_already_paid_order_stops_everything():
    decision = evaluate(case(), whatsapp(), ctx(entity_status="paid"))
    assert decision.blocked_by == "G09"


@pytest.mark.parametrize("state", ["RECOVERED", "EXHAUSTED", "CLOSED"])
def test_closed_cases_are_never_reopened(state):
    assert evaluate(case(state=state), whatsapp(), ctx()).blocked_by == "G10"


def test_a_promise_to_pay_is_honoured_until_its_date():
    future = (ctx()["now"] + timedelta(days=2)).isoformat()
    decision = evaluate(case(state="PROMISED", promise_date=future), whatsapp(), ctx())
    assert decision.blocked_by == "G10"
    assert decision.reason_code == "PROMISE_PENDING"


def test_a_lapsed_promise_stops_protecting_the_case():
    past = (ctx()["now"] - timedelta(days=1)).isoformat()
    assert evaluate(case(state="PROMISED", promise_date=past), whatsapp(), ctx()).allowed


# ----------------------------------------------------------- G11 ladder order

def test_voice_cannot_be_reached_without_spending_the_cheap_tiers():
    assert evaluate(case(touches_used=0), voice(), ctx()).blocked_by == "G11"


def test_tiers_cannot_be_skipped():
    decision = evaluate(case(touches_used=2), voice(), ctx(last_tier=0))
    assert decision.blocked_by == "G11"
    assert decision.reason_code == "TIER_SKIP"


def test_the_expected_voice_path_is_allowed():
    assert evaluate(case(touches_used=2), voice(), ctx(last_tier=2)).allowed


# ------------------------------------------------------------------ accounting

def test_a_block_records_the_spend_it_avoided():
    decision = evaluate(case(), whatsapp(cost=150), ctx(customer_touches_24h=1))
    assert decision.value_protected_paise == 150


def test_an_allowed_action_protects_nothing():
    decision = evaluate(case(), whatsapp(), ctx())
    assert decision.value_protected_paise == 0
    assert decision.compliance_risk_avoided_paise == 0
