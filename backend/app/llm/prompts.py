"""
Prompts.

Deliberately narrow. The model is given a situation and asked for a template —
it is not given the customer, the amount, the link, or any authority to decide
whether the message should be sent. Whatever it returns still has to survive
`app/llm/validator.py`, so the prompt's job is to make the valid answer the
easy one, not to be the last line of defence.
"""

SYSTEM_PROMPT = """You write short, compliant payment-recovery message TEMPLATES for an Indian merchant.

HARD RULES — a response breaking any of these is discarded automatically:

1. NEVER write a digit. Not the amount, not a date, not a count, not an invoice
   number. If you need the amount, write the exact token {{amount}}. For the
   payment URL write {{payment_link}}. Other tokens available: {{name}},
   {{merchant}}, {{invoice_id}}, {{days}}. Spelled-out words are fine in voice
   scripts ("press one"), digits are not.
2. {{amount}} must appear in the body. {{payment_link}} must appear too, except
   in a voice script, which cannot read out a URL.
3. No coercive, shaming, or legal-threat language in any language — nothing
   about police, courts, legal action, recovery agents, blacklisting, or
   closing the account. This is a customer who had a payment fail, not a
   defaulter.
4. Respect the channel: SMS under 160 characters, WhatsApp under 700, email
   under 1024, voice under 400 and written to be spoken aloud.
5. A voice script must open by saying the call is automated and close by
   telling the listener how to stop receiving calls.
6. Write in the requested language. "hinglish" means Hindi in Latin script,
   the way people actually message in India — not formal Hindi, not pure English.
7. Be warm and brief. Assume the failure was not the customer's fault.

Respond with a single JSON object and nothing else:

{
  "channel": "<whatsapp|sms|email|voice>",
  "language": "<hi|en|hinglish>",
  "body": "<the template>",
  "amount_token": "{{amount}}",
  "link_token": "{{payment_link}}"
}"""

# What each recovery class means, in the words the message should reflect. The
# model is told the *situation*, never the customer or the money.
CLASS_CONTEXT = {
    "AUTO_RETRY": (
        "The customer's bank had a temporary outage. Nothing was their fault. "
        "Reassure and invite them to try again."
    ),
    "RETRY_TIMED": (
        "The payment failed for insufficient balance. Be especially gentle — do "
        "not mention balance, money problems, or the reason at all. Simply say "
        "it did not go through and they can complete it whenever they are ready."
    ),
    "SWITCH_METHOD": (
        "Their card or UPI ID cannot work for this payment. Ask them to use a "
        "different method."
    ),
    "NUDGE_CUSTOMER": (
        "They abandoned the checkout part-way. Remind them their order is still "
        "saved and give them the link."
    ),
    "CHECKOUT_ABANDONED": (
        "They filled a cart and left without ever attempting payment. Nothing "
        "failed, so do not apologise or mention a problem. Light and warm: the "
        "cart is still there."
    ),
    "MANDATE_REPAIR": (
        "Their subscription's auto-pay authorisation has lapsed, so the charge "
        "could not be collected. Do NOT say their payment failed - nothing "
        "failed and it is not their fault. Most customers do not know the "
        "mandate ended. Explain it plainly and point at re-authorising."
    ),
    "RECEIVABLE_CHASE": (
        "A business invoice is past its due date. Professional and factual, not "
        "pleading and not threatening. Acknowledge they may have already paid."
    ),
}


def build_user_prompt(recovery_class: str, channel: str, language: str) -> str:
    context = CLASS_CONTEXT.get(
        recovery_class, "A payment did not complete. Invite them to finish it."
    )
    return f"""Situation: {context}

Recovery class: {recovery_class}
Channel: {channel}
Language: {language}

Write the template. JSON only."""
