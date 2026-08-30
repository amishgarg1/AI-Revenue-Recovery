"""
Escalation ladder.

Cheapest channel first, and no skipping. A voice call costs five times a
WhatsApp message and is far more intrusive, so it has to be earned: the cheap
tiers must have been tried and failed, the amount has to be worth the call, and
the customer has to have consented to voice.

The ladder proposes; the policy engine disposes. Nothing here sends anything —
`get_next_action` returns an *intent*, and every intent still has to clear all
eleven gates.
"""

from dataclasses import dataclass
from typing import Optional

# Tier -> (channel, cost in paise). Costs are the realistic Indian rates a
# merchant actually pays, which is what makes the ROI number meaningful.
# Which channel each rung uses. The channel is structural — tier 3 is the voice
# rung by definition — so it stays here. What each one *costs*, and the amount
# above which a call is worth placing, are a merchant's numbers and live in
# config/policy.yaml.
TIER_CHANNEL = {
    0: "silent",             # a retry against the gateway
    1: "whatsapp",
    2: "sms",
    3: "voice",
    4: "human",              # an agent's time
}


def tier_cost(tier: int, policy=None) -> int:
    from app.core import config
    return (policy or config.active()).tier_cost_paise[tier]


def voice_min_amount(policy=None) -> int:
    from app.core import config
    return (policy or config.active()).voice_min_amount_paise


def max_touches(policy=None) -> int:
    from app.core import config
    return (policy or config.active()).max_touches_per_case


# Kept as a module attribute because the analytics layer prices blocked actions
# from it. Reads the active policy on each access rather than freezing at
# import, so an operator who edits the file and reloads sees the new prices.
class _TierSpec:
    """`TIER_SPEC[tier]` -> (channel, cost) against the active policy."""

    def __getitem__(self, tier):
        return TIER_CHANNEL[tier], tier_cost(tier)

    def get(self, tier, default=None):
        if tier not in TIER_CHANNEL:
            return default
        return self[tier]


TIER_SPEC = _TierSpec()


@dataclass
class ActionIntent:
    tier: int
    channel: str
    cost_paise: int
    rationale: str


def _intent(tier: int, rationale: str, channel: Optional[str] = None,
            cost_paise: Optional[int] = None) -> ActionIntent:
    chan, cost = TIER_CHANNEL[tier], tier_cost(tier)
    return ActionIntent(tier=tier, channel=channel or chan,
                        cost_paise=cost if cost_paise is None else cost_paise,
                        rationale=rationale)


def get_next_action(recovery_class: str, touches_used: int, amount_paise: int,
                    consent_voice: bool = False) -> Optional[ActionIntent]:
    """
    The next rung for this case, or None if the ladder is finished.

    Returning None is a real outcome, not a failure: it means the case is
    exhausted and should stop consuming budget.
    """
    rc = recovery_class

    if rc == "DEAD":
        return None

    if rc == "MANUAL_REVIEW":
        # Never contacted automatically. It goes to a person exactly once, and
        # G07 will block it if anything tries to message it anyway.
        if touches_used == 0:
            return _intent(4, "risk-blocked: routed to a human, never auto-contacted")
        return None

    # Note what is *not* here: an attempt-count check. The ladder's job is to
    # name the cheapest next step; enforcing the attempt budget is G04's job.
    # Duplicating the rule here would mean the cap is enforced in two places and
    # audited in neither.

    # Infrastructure and balance failures start silent — a retry that costs
    # nothing and bothers nobody is strictly better than a message.
    if rc in ("AUTO_RETRY", "RETRY_TIMED"):
        if touches_used == 0:
            return _intent(0, "silent gateway retry before spending anything")
        if touches_used == 1:
            return _intent(1, "retry did not clear: first customer contact")
        return _intent(2, "no response on WhatsApp: cheaper SMS attempt")

    # The authorisation is gone, so there is nothing to retry against — a
    # silent attempt here is guaranteed to fail and would spend one of the
    # three attempts proving it. The only thing that can work is asking the
    # customer to authorise a new mandate.
    if rc == "MANDATE_REPAIR":
        if touches_used == 0:
            return _intent(1, "mandate revoked: re-authorisation link, no retry")
        if touches_used == 1:
            return _intent(2, "no re-authorisation yet: SMS with the same link")
        return _intent(2, "final reminder before the subscription is written off")

    # Nothing failed — the customer never got as far as paying. There is no
    # error to explain and no retry to make, so the first and only lever is a
    # reminder that their cart is still there.
    if rc == "CHECKOUT_ABANDONED":
        if touches_used == 0:
            return _intent(1, "cart still held: one reminder with a direct link")
        if touches_used == 1:
            return _intent(2, "no return: single SMS, then stop")
        # Deliberately shorter than the other ladders. Somebody who ignored two
        # reminders about a cart they abandoned is not a debtor; pushing a third
        # time buys irritation.
        return None

    # The customer has to *do* something (fix a VPA, use another card, finish
    # authentication), so a silent retry cannot help. Start at Tier 1.
    if rc in ("NUDGE_CUSTOMER", "SWITCH_METHOD"):
        if touches_used == 0:
            return _intent(1, "customer action required: actionable link on WhatsApp")
        return _intent(2, "no response: SMS fallback")

    # B2B receivables are the one lane that earns a voice call. The rungs are
    # email -> WhatsApp -> voice; WhatsApp sits at tier 2 rather than tier 1 so
    # the escalation is monotonic and G11's no-skipping rule can be enforced
    # literally, instead of being special-cased for this lane.
    if rc == "RECEIVABLE_CHASE":
        if touches_used == 0:
            return _intent(1, "polite email reminder with the invoice link",
                           channel="email")
        if touches_used == 1:
            return _intent(2, "no reply to the email: WhatsApp reminder",
                           channel="whatsapp", cost_paise=tier_cost(1))
        if amount_paise >= voice_min_amount() and consent_voice:
            return _intent(3, "high-value invoice, voice consent on file: "
                              "Hinglish call with a promise-to-pay option")
        return _intent(2, "below the voice threshold or no voice consent: SMS instead")

    return None
