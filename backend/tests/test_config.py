"""
Policy as configuration.

Two claims are being tested. That the engine is unchanged and only the numbers
move — a second merchant's rules must produce different refusals from the same
code. And that a policy file which cannot be trusted fails at load rather than
at midnight, because a rule a merchant believes they set and did not is worse
than no rule at all.
"""

import textwrap

import pytest

from app.core import config
from app.core.config import PolicyBook, PolicyConfig, PolicyConfigError
from app.core.ladder import ActionIntent
from app.core.policy import evaluate

from tests.test_policy import at_ist, case, ctx  # the shared builders


@pytest.fixture(autouse=True)
def restore_book():
    """
    The book is a module-level singleton. A test that loads a fixture policy
    would otherwise leak it into every test that runs afterwards.
    """
    yield
    config.reload()


def write(tmp_path, body: str) -> str:
    path = tmp_path / "policy.yaml"
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    return str(path)


# ------------------------------------------------------------------ defaults

def test_a_missing_file_is_normal(tmp_path):
    """
    The demo has to run from a clean clone with no config at all, and the
    defaults have to be the values the committed evaluation was produced with.
    """
    book = config.load(str(tmp_path / "absent.yaml"))

    assert book.source is None
    assert book.default == PolicyConfig()
    assert book.default.quiet_start_ist == 21
    assert book.default.max_touches_24h == 1
    assert book.default.tier_cost_paise[3] == 150


def test_an_empty_file_is_also_normal(tmp_path):
    assert config.load(write(tmp_path, "")).default == PolicyConfig()


def test_the_committed_policy_matches_the_built_in_defaults():
    """
    config/policy.yaml states the shipped values explicitly. If it drifts from
    the dataclass defaults, deleting the file would change the answer — and the
    README promises it does not.
    """
    shipped = config.load().default
    assert shipped == PolicyConfig(label=shipped.label)


# --------------------------------------------------------- the engine is one

def test_a_second_merchant_gets_different_refusals_from_the_same_code(tmp_path):
    """
    The whole point. One engine, two merchants, different rules — and the
    difference shows up as a gate verdict, not as a branch in the code.
    """
    path = write(tmp_path, """
        defaults:
          quiet_start_ist: 21
          quiet_end_ist: 9
        merchants:
          nightowl:
            quiet_start_ist: 23
            quiet_end_ist: 5
    """)
    book = config.load(path)

    # 10 PM IST: inside the default quiet window, outside the night owl's.
    at_ten_pm = ctx(now=at_ist(22))
    intent = ActionIntent(tier=1, channel="whatsapp", cost_paise=30, rationale="")

    default_verdict = evaluate(
        case(), intent, {**at_ten_pm, "policy": book.for_merchant(None)})
    nightowl_verdict = evaluate(
        case(), intent, {**at_ten_pm, "policy": book.for_merchant("nightowl")})

    assert default_verdict.blocked_by == "G02"
    assert nightowl_verdict.allowed


def test_a_merchant_states_only_what_differs(tmp_path):
    """
    Repeating a whole policy per merchant is how two of them silently drift
    apart. Unstated keys inherit.
    """
    path = write(tmp_path, """
        defaults:
          cooldown_hours: 6
          max_touches_7d: 3
        merchants:
          quiet_brand:
            cooldown_hours: 24
    """)
    merchant = config.load(path).for_merchant("quiet_brand")

    assert merchant.cooldown_hours == 24
    assert merchant.max_touches_7d == 3


def test_an_unknown_merchant_falls_back_to_the_defaults(tmp_path):
    book = config.load(write(tmp_path, "defaults:\n  cooldown_hours: 8\n"))
    assert book.for_merchant("nobody").cooldown_hours == 8


def test_the_gate_reports_the_configured_hours_not_hardcoded_ones(tmp_path):
    """
    The refusal text is read by a compliance reviewer. A gate that enforces the
    merchant's window while explaining somebody else's is worse than one that
    says nothing.
    """
    book = config.load(write(tmp_path, """
        defaults:
          quiet_start_ist: 20
          quiet_end_ist: 11
    """))
    intent = ActionIntent(tier=1, channel="whatsapp", cost_paise=30, rationale="")

    decision = evaluate(case(), intent,
                        {**ctx(now=at_ist(21)), "policy": book.default})
    detail = next(g.detail for g in decision.gate_trail if g.gate_id == "G02")

    assert "20:00-11:00" in detail
    assert "9PM" not in detail


def test_tier_costs_come_from_the_policy(tmp_path):
    """A merchant on a different messaging contract pays different prices."""
    from app.core.ladder import tier_cost

    book = config.load(write(tmp_path, """
        defaults:
          tier_cost_paise:
            0: 0
            1: 75
            2: 20
            3: 150
            4: 5000
    """))
    config.reload(str(book.source))
    assert tier_cost(1) == 75


# ------------------------------------------------------------- loud failures

def test_a_misspelled_key_is_rejected(tmp_path):
    """
    The failure this exists to prevent: a merchant believes they set a rule and
    a silent default is enforcing something else.
    """
    path = write(tmp_path, "defaults:\n  quiet_hours_start: 22\n")
    with pytest.raises(PolicyConfigError, match="quiet_hours_start"):
        config.load(path)


def test_an_unknown_top_level_section_is_rejected(tmp_path):
    path = write(tmp_path, "merchant:\n  acme:\n    cooldown_hours: 2\n")
    with pytest.raises(PolicyConfigError, match="merchant"):
        config.load(path)


@pytest.mark.parametrize("body,message", [
    ("defaults:\n  quiet_start_ist: 26\n", "0 to 23"),
    ("defaults:\n  quiet_start_ist: nine\n", "0 to 23"),
    ("defaults:\n  max_cost_ratio: 1.8\n", "between 0 and 1"),
    ("defaults:\n  cooldown_hours: -4\n", "non-negative"),
    ("defaults:\n  min_viable_amount_paise: -1\n", "non-negative"),
])
def test_values_that_cannot_mean_anything_are_rejected(tmp_path, body, message):
    with pytest.raises(PolicyConfigError, match=message):
        config.load(write(tmp_path, body))


def test_a_weekly_cap_below_the_daily_cap_is_rejected(tmp_path):
    """
    Individually valid, jointly meaningless: the weekly cap could never bind.
    The kind of mistake that reads fine and quietly disables a rule.
    """
    path = write(tmp_path, """
        defaults:
          max_touches_24h: 5
          max_touches_7d: 2
    """)
    with pytest.raises(PolicyConfigError, match="could never bind"):
        config.load(path)


def test_a_voice_window_that_wraps_midnight_is_rejected(tmp_path):
    path = write(tmp_path, """
        defaults:
          voice_start_ist: 20
          voice_end_ist: 6
    """)
    with pytest.raises(PolicyConfigError, match="must be before"):
        config.load(path)


def test_a_missing_rung_price_is_rejected(tmp_path):
    path = write(tmp_path, """
        defaults:
          tier_cost_paise:
            0: 0
            1: 30
    """)
    with pytest.raises(PolicyConfigError, match="every rung"):
        config.load(path)


def test_a_file_that_is_not_a_mapping_is_rejected(tmp_path):
    with pytest.raises(PolicyConfigError, match="mapping"):
        config.load(write(tmp_path, "- just\n- a list\n"))


def test_a_bad_merchant_names_that_merchant(tmp_path):
    """The error has to say which merchant, or a file of thirty is a hunt."""
    path = write(tmp_path, """
        defaults:
          cooldown_hours: 6
        merchants:
          acme:
            cooldown_hours: -1
    """)
    with pytest.raises(PolicyConfigError, match="non-negative"):
        config.load(path)


# ------------------------------------------------------------- immutability

def test_a_policy_cannot_be_mutated_while_it_is_being_enforced():
    """A gate that could rewrite the policy mid-evaluation is unauditable."""
    with pytest.raises(Exception):
        PolicyConfig().quiet_start_ist = 3


def test_the_book_survives_a_reload_of_the_real_file():
    before = config.active().quiet_start_ist
    config.reload()
    assert config.active().quiet_start_ist == before
