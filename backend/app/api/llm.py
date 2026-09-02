"""
The LLM guardrail, exposed so it can be exercised rather than described.

The project's one architectural claim is that the LLM never touches a rupee,
and the thing that enforces it is `app/llm/validator.py`. Until now that ran
only inside the test suite, which means the claim arrived as an assertion:
"trust us, a validator rejects this."

These endpoints let anyone throw a draft at the real validator — the same
function the batch calls — and watch each check pass or fail. The adversarial
samples are the outputs a model actually produces when told not to write
numbers: a rupee figure, a due date, an order id, a legal threat, a voice
script missing its opt-out.

None of this needs an API key. The validator is the interesting part and it is
ours, not the provider's.
"""

from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.llm.client import call_count, render
from app.llm.fallback import get_fallback_template
from app.llm.validator import (
    BANNED_PHRASES, CHANNEL_LENGTH_CAPS, validate,
)
from app.models import Action, Case, Customer, Invoice

router = APIRouter(prefix="/api", tags=["llm"])


def _draft(channel: str, language: str, body: str) -> str:
    import json
    return json.dumps({
        "channel": channel,
        "language": language,
        "body": body,
        "amount_token": "{{amount}}",
        "link_token": "{{payment_link}}",
    })


# Each sample is a real failure mode, not a strawman. A model told "never write
# a number" will still write one when the situation seems to demand it — a due
# date, a count of days, an order reference — and every one of those is a rupee
# figure waiting to happen.
SAMPLES = [
    {
        "id": "clean",
        "label": "A well-formed draft",
        "note": "What the model is asked for: tokens, no digits, no pressure.",
        "expect": "pass",
        "channel": "whatsapp",
        "language": "en",
        "body": "Hi {{name}}, your payment of {{amount}} did not go through. "
                "You can complete it here: {{payment_link}}",
    },
    {
        "id": "wrote_the_amount",
        "label": "The model wrote the rupee figure itself",
        "note": "The failure the whole architecture exists to prevent. The "
                "amount looks right — and it is the model's guess, not the "
                "database's value.",
        "expect": "reject",
        "channel": "whatsapp",
        "language": "en",
        "body": "Hi {{name}}, your payment of Rs 1,499 did not go through. "
                "Complete it here: {{payment_link}} for {{amount}}",
    },
    {
        "id": "wrote_a_date",
        "label": "A number that is not money",
        "note": "Subtler and just as wrong: nothing told the model how many "
                "days overdue this is, so it invented one.",
        "expect": "reject",
        "channel": "email",
        "language": "en",
        "body": "Hi {{name}}, invoice {{invoice_id}} for {{amount}} is 14 days "
                "overdue. Settle it here: {{payment_link}}",
    },
    {
        "id": "dropped_the_link",
        "label": "Missing a token the renderer needs",
        "note": "Renders into a message with no way to pay.",
        "expect": "reject",
        "channel": "whatsapp",
        "language": "en",
        "body": "Hi {{name}}, your payment of {{amount}} is still pending. "
                "Please complete it at your earliest convenience.",
    },
    {
        "id": "legal_threat",
        "label": "Coercive language",
        "note": "A model asked to be persuasive reaches for this unprompted. "
                "The list covers Hindi too — kanooni, adalat, vasooli.",
        "expect": "reject",
        "channel": "sms",
        "language": "en",
        "body": "{{name}}, pay {{amount}} now or we will begin legal action. "
                "{{payment_link}}",
    },
    {
        "id": "hinglish_threat",
        "label": "Coercive language, in Hinglish",
        "note": "An English-only banned list would have passed this.",
        "expect": "reject",
        "channel": "whatsapp",
        "language": "hinglish",
        "body": "{{name}} ji, {{amount}} turant bhariye warna kanooni karyavahi "
                "hogi. {{payment_link}}",
    },
    {
        "id": "sms_too_long",
        "label": "Over the SMS length cap",
        "note": "Silently split by the carrier and billed twice.",
        "expect": "reject",
        "channel": "sms",
        "language": "en",
        "body": "Hello {{name}}, we are reaching out because your recent payment "
                "of {{amount}} could not be processed successfully by your bank "
                "and we would really like to help you complete it whenever you "
                "are ready: {{payment_link}}",
    },
    {
        "id": "voice_no_optout",
        "label": "A voice script with no way out",
        "note": "An automated call must say it is automated and must offer an "
                "opt-out. This one does neither.",
        "expect": "reject",
        "channel": "voice",
        "language": "hinglish",
        "body": "Namaste {{name}} ji, aapka {{amount}} pending hai. Kripya "
                "jaldi payment kar dijiye.",
    },
    {
        "id": "voice_clean",
        "label": "A compliant Hinglish voice script",
        "note": "Discloses that it is automated, spells its numbers as words, "
                "and ends with the opt-out.",
        "expect": "pass",
        "channel": "voice",
        "language": "hinglish",
        "body": "Namaste {{name}} ji. Yeh {{merchant}} ki taraf se automated "
                "reminder call hai. Aapka invoice {{invoice_id}}, amount "
                "{{amount}}, pending hai. Date confirm karne ke liye ek "
                "dabaiye, calls band karne ke liye nau dabaiye.",
    },
]


class DraftIn(BaseModel):
    body: str
    channel: str = "whatsapp"
    language: str = "en"
    recovery_class: str = "NUDGE_CUSTOMER"


@router.get("/llm/samples")
def samples():
    """Adversarial and clean drafts to run through the validator."""
    return {
        "samples": SAMPLES,
        "banned_phrases": BANNED_PHRASES,
        "length_caps": CHANNEL_LENGTH_CAPS,
        "llm_calls_this_process": call_count(),
    }


def substitution_values(db: Session):
    """
    The values a real send would substitute, read from a real case.

    These were hardcoded once — a customer name, an amount and a payment link
    that belonged to no case in the batch — under a comment claiming they came
    from the database. So the playground rendered a message that could not
    have been sent, which is precisely the confusion this endpoint exists to
    dispel: the whole point is that the figures come from the database and not
    from a model.

    The case is the first one the batch actually sent a message to, ordered by
    id, so the rendered preview is a message a viewer can go and find on the
    case page. Returns None when the batch has not been run.
    """
    action = (
        db.query(Action)
        .filter(Action.status == "SENT", Action.message_body.isnot(None))
        .order_by(Action.case_id)
        .first()
    )
    if action is None:
        return None, None

    case = db.query(Case).filter(Case.case_id == action.case_id).first()
    customer = db.query(Customer).filter(
        Customer.customer_id == action.customer_id
    ).first()
    if case is None or customer is None:
        return None, None

    invoice = db.query(Invoice).filter(
        Invoice.invoice_id == case.entity_id
    ).first()

    # Rendered exactly as the orchestrator renders them, so the preview and the
    # real send cannot drift apart.
    return case.case_id, {
        "name": customer.name,
        "amount": f"Rs {case.amount_at_risk_paise / 100:,.2f}",
        "payment_link": action.payment_link_url or "",
        "merchant": "Demo Merchant",
        "invoice_id": case.entity_id,
        "days": str(getattr(invoice, "days_overdue", "") or ""),
    }


@router.post("/llm/validate")
def validate_draft(draft: DraftIn, db: Session = Depends(get_db)):
    """
    Run one draft through the real validator and report every check.

    Also returns what would actually have been sent: the rendered message if
    the draft passes, or the deterministic fallback if it does not. That second
    half is the point — a rejection is not an outage, it is a downgrade.
    """
    raw = _draft(draft.channel, draft.language, draft.body)
    result = validate(raw, {"language": draft.language, "channel": draft.channel})

    case_id, values = substitution_values(db)

    fallback = get_fallback_template(
        draft.recovery_class, draft.channel, draft.language
    )
    template = draft.body if result.ok else fallback

    return {
        "ok": result.ok,
        "reason": result.reason,
        "checks": result.checks,
        # With no batch in the database there are no real values to substitute,
        # and inventing some is what got this wrong the first time. Show the
        # template with its tokens intact and say where the values would come
        # from.
        "would_send": render(template, values) if values else template,
        "values_from_case": case_id,
        "used": "llm_template" if result.ok else "deterministic_fallback",
        "fallback_template": fallback,
    }
