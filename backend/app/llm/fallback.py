"""
Deterministic message templates.

These are the safety net under the LLM. When the model is unavailable, returns
malformed JSON, or writes something the validator rejects, the batch keeps
running on these — same placeholders, same compliance properties, no numbers
authored by anything other than Python.

They are also what runs when no API key is configured at all, which is how a
judge cloning this repo will first see it. That is deliberate: the demo must
not require our credentials.

Every template obeys the same contract the model is held to: `{{amount}}` and
`{{payment_link}}` are tokens, never literals; no coercive or legal-threat
language in any language; voice scripts open with an automated-call disclosure
and close with an opt-out.
"""

# (recovery_class, language) -> template. `language` is one of hi | en | hinglish.
_TEXT = {
    ("SWITCH_METHOD", "en"):
        "Hi {{name}}, your payment of {{amount}} could not go through with the "
        "method you used. You can complete it with a different card or UPI ID "
        "here: {{payment_link}}",
    ("SWITCH_METHOD", "hi"):
        "Namaste {{name}}, aapka {{amount}} ka payment jis method se kiya tha "
        "usse complete nahi ho paaya. Aap doosre card ya UPI se yahan pura kar "
        "sakte hain: {{payment_link}}",
    ("SWITCH_METHOD", "hinglish"):
        "Hi {{name}}, aapka {{amount}} ka payment method issue ki wajah se fail "
        "ho gaya. Doosre card ya UPI se yahan complete kijiye: {{payment_link}}",

    ("RETRY_TIMED", "en"):
        "Hi {{name}}, your payment of {{amount}} did not go through. Whenever "
        "you are ready, you can complete it here: {{payment_link}}",
    ("RETRY_TIMED", "hi"):
        "Namaste {{name}}, aapka {{amount}} ka payment complete nahi ho paaya. "
        "Jab aapko theek lage, yahan se pura kar sakte hain: {{payment_link}}",
    ("RETRY_TIMED", "hinglish"):
        "Hi {{name}}, {{amount}} ka payment complete nahi hua. Jab convenient "
        "ho, yahan se kar dijiye: {{payment_link}}",

    ("NUDGE_CUSTOMER", "en"):
        "Hi {{name}}, you left a payment of {{amount}} unfinished. Your order is "
        "still saved - you can finish it here: {{payment_link}}",
    ("NUDGE_CUSTOMER", "hi"):
        "Namaste {{name}}, aapka {{amount}} ka payment adhura reh gaya tha. "
        "Aapka order abhi bhi safe hai, yahan se pura kijiye: {{payment_link}}",
    ("NUDGE_CUSTOMER", "hinglish"):
        "Hi {{name}}, {{amount}} ka payment adhura reh gaya tha. Order abhi bhi "
        "saved hai - yahan complete kar lijiye: {{payment_link}}",

    ("CHECKOUT_ABANDONED", "en"):
        "Hi {{name}}, your cart is still saved. {{amount}} to check out whenever "
        "you are ready: {{payment_link}}",
    ("CHECKOUT_ABANDONED", "hi"):
        "Namaste {{name}}, aapka cart abhi bhi saved hai. {{amount}} ka payment "
        "jab chahein yahan kar sakte hain: {{payment_link}}",
    ("CHECKOUT_ABANDONED", "hinglish"):
        "Hi {{name}}, aapka cart abhi bhi saved hai. {{amount}} ka checkout jab "
        "convenient ho yahan kar lijiye: {{payment_link}}",

    # Never says "your payment failed" — nothing failed. The subscription
    # simply stopped, and most customers do not know it has.
    ("MANDATE_REPAIR", "en"):
        "Hi {{name}}, the auto-pay permission for your subscription has ended, "
        "so we could not collect {{amount}}. You can set it up again in one "
        "step here: {{payment_link}}",
    ("MANDATE_REPAIR", "hi"):
        "Namaste {{name}}, aapki subscription ki auto-pay permission khatam ho "
        "gayi hai, isliye {{amount}} collect nahi ho paaya. Yahan se dobara "
        "set kar sakte hain: {{payment_link}}",
    ("MANDATE_REPAIR", "hinglish"):
        "Hi {{name}}, aapki subscription ka auto-pay mandate expire ho gaya hai, "
        "isliye {{amount}} nahi kat paaya. Ek step mein dobara set kijiye: "
        "{{payment_link}}",

    ("RECEIVABLE_CHASE", "en"):
        "Hello {{name}}, this is a reminder from {{merchant}} about invoice "
        "{{invoice_id}} for {{amount}}, which is now {{days}} days past its due "
        "date. You can settle it here: {{payment_link}}. If it has already been "
        "paid, please ignore this message.",
    ("RECEIVABLE_CHASE", "hi"):
        "Namaste {{name}}, {{merchant}} ki taraf se invoice {{invoice_id}} ke "
        "liye reminder hai. Amount {{amount}} hai aur due date se {{days}} din "
        "ho chuke hain. Yahan se payment kar sakte hain: {{payment_link}}. Agar "
        "already pay kar diya hai to is message ko ignore kijiye.",
    ("RECEIVABLE_CHASE", "hinglish"):
        "Hi {{name}}, {{merchant}} se reminder - invoice {{invoice_id}}, amount "
        "{{amount}}, due date se {{days}} din ho gaye hain. Payment yahan kijiye: "
        "{{payment_link}}. Already paid ho to ignore kar dijiye.",

    ("AUTO_RETRY", "en"):
        "Hi {{name}}, your bank could not process {{amount}} earlier due to a "
        "temporary issue on their side. It should work now: {{payment_link}}",
    ("AUTO_RETRY", "hi"):
        "Namaste {{name}}, bank ki taraf se temporary dikkat ki wajah se "
        "{{amount}} ka payment nahi ho paaya tha. Ab ho jaana chahiye: "
        "{{payment_link}}",
    ("AUTO_RETRY", "hinglish"):
        "Hi {{name}}, bank side pe temporary issue tha isliye {{amount}} ka "
        "payment nahi hua. Ab try kijiye: {{payment_link}}",
}

# Voice is separate: shorter, spoken, and legally required to disclose that it
# is automated and to offer an opt-out. Both are in the script, not in a policy
# document somewhere.
_VOICE = {
    "en":
        "Hello {{name}}. This is an automated reminder call from {{merchant}}. "
        "Your invoice {{invoice_id}} for {{amount}} has been pending for "
        "{{days}} days. We have sent a payment link on WhatsApp. To confirm a "
        "payment date press one, to be called back later press two, and to stop "
        "these calls press nine.",
    "hi":
        "Namaste {{name}} ji. Main {{merchant}} ki taraf se ek automated "
        "reminder call kar raha hoon. Aapka invoice {{invoice_id}}, amount "
        "{{amount}}, {{days}} din se pending hai. Payment ke liye humne aapko "
        "WhatsApp par link bheja hai. Payment date confirm karne ke liye ek "
        "dabaiye, baad mein call ke liye do, aur aage calls band karne ke liye "
        "nau dabaiye.",
    "hinglish":
        "Namaste {{name}} ji. Yeh {{merchant}} ki taraf se automated reminder "
        "call hai. Aapka invoice {{invoice_id}}, amount {{amount}}, {{days}} din "
        "se pending hai. Payment link WhatsApp par bhej diya hai. Date confirm "
        "karne ke liye ek dabaiye, baad mein call ke liye do, calls band karne "
        "ke liye nau dabaiye.",
}

_SMS_FALLBACK = {
    "en": "Hi {{name}}, {{amount}} is still pending. Complete it here: {{payment_link}}",
    "hi": "Namaste {{name}}, {{amount}} pending hai. Yahan pura kijiye: {{payment_link}}",
    "hinglish": "Hi {{name}}, {{amount}} pending hai. Yahan complete kijiye: {{payment_link}}",
}


def get_fallback_template(recovery_class: str, channel: str, language: str) -> str:
    lang = language if language in ("en", "hi", "hinglish") else "en"

    if channel == "voice":
        return _VOICE[lang]

    # SMS has a 160-character budget, so it drops the context and keeps the link.
    if channel == "sms":
        return _SMS_FALLBACK[lang]

    template = _TEXT.get((recovery_class, lang))
    if template:
        return template
    return _TEXT[("NUDGE_CUSTOMER", lang)]
