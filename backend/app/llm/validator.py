"""
The LLM guardrail.

Every model output passes through here before it can become a message. The
check that matters most is the second one: **no literal digits in the body.**

The model is not asked politely to avoid numbers — it is mechanically prevented
from emitting one. If it writes "your payment of Rs 1,499 is pending", the
draft is rejected and a deterministic template is used instead. The only way a
rupee figure reaches a customer is by Python substituting `{{amount}}` with a
value read from the database.

That single rule is what turns "the LLM never touches a rupee" from a claim
into a property of the system. Everything else here — schema, required tokens,
banned coercive language in English and Hindi, per-channel length caps, the
mandatory disclosure and opt-out on voice scripts — is enforcement of the same
idea: the model drafts, the code decides.
"""

import re
from typing import Optional

from pydantic import BaseModel, Field

# Coercive and legal-threat language, in the languages we actually send in.
# Debt-collection messaging that threatens legal consequences is both a
# compliance problem and a brand problem, and a model asked to be "persuasive"
# reaches for it unprompted.
BANNED_PHRASES = [
    # English
    "legal action", "legal notice", "police", "court", "criminal", "arrest",
    "blacklist", "recovery agent", "account will be closed", "seize",
    "defaulter", "prosecution", "lawsuit",
    # Hindi / Hinglish
    "kanooni", "kanuni", "police case", "adalat", "adaalat", "vasooli",
    "notice bhej", "case kar", "jail",
]

# Voice calls carry obligations text messages do not.
VOICE_DISCLOSURE_HINTS = ["automated", "recorded"]
VOICE_OPTOUT_HINTS = ["press nine", "dabaiye", "press 9", "opt out", "stop these calls"]

CHANNEL_LENGTH_CAPS = {"sms": 160, "whatsapp": 700, "email": 1024, "voice": 400}

VALID_CHANNELS = {"whatsapp", "sms", "email", "voice"}
VALID_LANGUAGES = {"hi", "en", "hinglish"}

PLACEHOLDER = re.compile(r"\{\{\s*\w+\s*\}\}")


class DraftMessage(BaseModel):
    channel: str
    language: str
    body: str = Field(max_length=1024)
    amount_token: str
    link_token: str


class ValidationResult(BaseModel):
    ok: bool
    reason: Optional[str] = None
    checks: dict = {}


def _fail(reason: str, checks: dict) -> ValidationResult:
    return ValidationResult(ok=False, reason=reason, checks=checks)


def validate(raw: str, ctx: dict) -> ValidationResult:
    """
    Validate one raw model response.

    `ctx` carries what we asked for — `language`, and optionally `channel` — so
    a model that answers a different question than the one asked is caught
    rather than sent.
    """
    checks: dict = {}

    # 1. Well-formed JSON matching the schema we asked for.
    try:
        draft = DraftMessage.model_validate_json(raw)
        checks["schema"] = True
    except Exception as exc:
        return _fail(f"SCHEMA_FAIL:{type(exc).__name__}", {"schema": False})

    body = draft.body
    stripped = PLACEHOLDER.sub("", body)

    # 2. The load-bearing check. Placeholders are removed first, so `{{amount}}`
    #    is fine and "1,499" is not.
    digits = re.findall(r"\d", stripped)
    checks["no_literal_numbers"] = not digits
    if digits:
        return _fail(f"LLM_WROTE_A_NUMBER:{''.join(digits[:8])}", checks)

    # 3. The tokens the renderer needs must actually be present, or the message
    #    goes out without the amount or without the link.
    checks["has_amount_token"] = "{{amount}}" in body
    checks["has_link_token"] = "{{payment_link}}" in body
    if not checks["has_amount_token"]:
        return _fail("MISSING_TOKEN:amount", checks)
    # A voice script cannot read out a URL, so it references the link sent by
    # message instead of embedding one.
    if draft.channel != "voice" and not checks["has_link_token"]:
        return _fail("MISSING_TOKEN:payment_link", checks)

    # 4. Compliance.
    low = body.lower()
    hit = next((p for p in BANNED_PHRASES if p in low), None)
    checks["compliance"] = hit is None
    if hit:
        return _fail(f"BANNED_PHRASE:{hit}", checks)

    # 5. Channel length. An SMS that overflows is silently split and billed twice.
    cap = CHANNEL_LENGTH_CAPS.get(draft.channel, 1024)
    checks["length"] = len(body) <= cap
    checks["length_used"] = len(body)
    if not checks["length"]:
        return _fail(f"TOO_LONG:{len(body)}>{cap}", checks)

    # 6. The model answered the question we asked.
    checks["channel_valid"] = draft.channel in VALID_CHANNELS
    if not checks["channel_valid"]:
        return _fail(f"BAD_CHANNEL:{draft.channel}", checks)

    requested_channel = ctx.get("channel")
    if requested_channel and draft.channel != requested_channel:
        checks["channel_match"] = False
        return _fail(f"CHANNEL_MISMATCH:{draft.channel}!={requested_channel}", checks)
    checks["channel_match"] = True

    checks["language"] = draft.language == ctx.get("language")
    if not checks["language"]:
        return _fail(f"LANG_MISMATCH:{draft.language}!={ctx.get('language')}", checks)

    # 7. Voice-only obligations: say it is automated, offer a way out.
    if draft.channel == "voice":
        checks["voice_disclosure"] = any(h in low for h in VOICE_DISCLOSURE_HINTS)
        if not checks["voice_disclosure"]:
            return _fail("MISSING_AUTOMATED_CALL_DISCLOSURE", checks)
        checks["voice_optout"] = any(h in low for h in VOICE_OPTOUT_HINTS)
        if not checks["voice_optout"]:
            return _fail("MISSING_OPTOUT_INSTRUCTION", checks)

    return ValidationResult(ok=True, reason=None, checks=checks)
