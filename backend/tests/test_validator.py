"""
Validator tests.

The claim "the LLM never touches a rupee" is only true if this file is true, so
the digit check gets the most attention — including the ways a model actually
writes numbers when told not to.
"""

import json

import pytest

from app.llm.client import render
from app.llm.validator import validate


def draft(**overrides) -> str:
    base = {
        "channel": "whatsapp",
        "language": "en",
        "body": "Hi {{name}}, your payment of {{amount}} is pending. "
                "Complete it here: {{payment_link}}",
        "amount_token": "{{amount}}",
        "link_token": "{{payment_link}}",
    }
    base.update(overrides)
    return json.dumps(base)


def ctx(language="en", channel="whatsapp") -> dict:
    return {"language": language, "channel": channel}


def test_a_well_formed_draft_passes():
    result = validate(draft(), ctx())
    assert result.ok
    assert result.checks["no_literal_numbers"]


def test_malformed_json_is_rejected():
    assert not validate("not json at all", ctx()).ok
    assert validate("{}", ctx()).reason.startswith("SCHEMA_FAIL")


# ------------------------------------------------------- the load-bearing check

@pytest.mark.parametrize("body", [
    "Hi {{name}}, pay Rs 1499 here: {{payment_link}} for {{amount}}",
    "Your {{amount}} is 3 days overdue. {{payment_link}}",
    "Pay {{amount}} before 5pm today: {{payment_link}}",
    "{{amount}} pending on order 88213. {{payment_link}}",
])
def test_any_literal_digit_is_rejected(body):
    result = validate(draft(body=body), ctx())
    assert not result.ok
    assert result.reason.startswith("LLM_WROTE_A_NUMBER")


def test_digits_inside_placeholders_do_not_count():
    """`{{amount}}` renders to a number later; that is the point, not a violation."""
    body = "Hi {{name}}, {{amount}} for {{invoice_id}}: {{payment_link}}"
    assert validate(draft(body=body), ctx()).ok


def test_spelled_out_numbers_are_allowed_in_voice_scripts():
    body = ("Hello {{name}}. This is an automated call about {{amount}}. "
            "Press one to confirm, or press nine to stop these calls.")
    assert validate(draft(channel="voice", body=body), ctx(channel="voice")).ok


# ------------------------------------------------------------------ tokens

def test_a_message_without_the_amount_token_is_rejected():
    body = "Hi {{name}}, your payment is pending: {{payment_link}}"
    assert validate(draft(body=body), ctx()).reason == "MISSING_TOKEN:amount"


def test_a_message_without_a_link_is_rejected():
    body = "Hi {{name}}, your payment of {{amount}} is pending."
    assert validate(draft(body=body), ctx()).reason == "MISSING_TOKEN:payment_link"


def test_voice_may_omit_the_link_because_it_cannot_read_a_url():
    body = ("Hello {{name}}, this is an automated call. {{amount}} is pending "
            "and we sent a link by message. Press nine to stop these calls.")
    assert validate(draft(channel="voice", body=body), ctx(channel="voice")).ok


# -------------------------------------------------------------- compliance

@pytest.mark.parametrize("phrase", [
    "legal action", "police case", "kanooni", "adalat",
    "recovery agent", "your account will be closed", "blacklist",
])
def test_coercive_language_is_rejected_in_english_and_hindi(phrase):
    body = f"Hi {{{{name}}}}, pay {{{{amount}}}} or we will take {phrase}. {{{{payment_link}}}}"
    result = validate(draft(body=body), ctx())
    assert not result.ok
    assert result.reason.startswith("BANNED_PHRASE")


def test_an_sms_over_the_carrier_limit_is_rejected():
    body = "{{amount}} {{payment_link}} " + "x" * 200
    result = validate(draft(channel="sms", body=body), ctx(channel="sms"))
    assert result.reason.startswith("TOO_LONG")


def test_the_model_must_answer_in_the_requested_language():
    assert validate(draft(language="hi"), ctx(language="en")).reason \
        .startswith("LANG_MISMATCH")


def test_the_model_must_answer_for_the_requested_channel():
    assert validate(draft(channel="sms"), ctx(channel="whatsapp")).reason \
        .startswith("CHANNEL_MISMATCH")


def test_voice_must_disclose_that_it_is_automated():
    body = ("Hello {{name}}, {{amount}} is pending. Press nine to stop "
            "these calls.")
    result = validate(draft(channel="voice", body=body), ctx(channel="voice"))
    assert result.reason == "MISSING_AUTOMATED_CALL_DISCLOSURE"


def test_voice_must_offer_an_opt_out():
    body = "Hello {{name}}, this is an automated call. {{amount}} is pending."
    result = validate(draft(channel="voice", body=body), ctx(channel="voice"))
    assert result.reason == "MISSING_OPTOUT_INSTRUCTION"


# ------------------------------------------------------------------ rendering

def test_rendering_substitutes_only_values_the_database_supplied():
    body = render("Hi {{name}}, pay {{amount}} at {{payment_link}}", {
        "name": "Meera", "amount": "Rs 1,499.00",
        "payment_link": "https://rzp.io/x",
    })
    assert body == "Hi Meera, pay Rs 1,499.00 at https://rzp.io/x"


def test_an_unknown_placeholder_stays_visible_instead_of_vanishing():
    """A message reading `{{days}}` is an obvious bug; a blank gap ships."""
    assert render("{{days}} days", {}) == "{{days}} days"
