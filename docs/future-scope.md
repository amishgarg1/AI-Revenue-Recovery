# Future scope

What was deliberately left out, and why. Scope was cut so that what exists
actually works — a demo with six half-finished lanes is worth less than one with
two that survive questioning.

---

## Cut on purpose

### Live telephony

Voice scripts are drafted, validated (automated-call disclosure, opt-out
instruction, no coercive language in English or Hindi, 400-character cap) and
rendered end to end. What is missing is dialling: no SIP trunk, no DTMF capture,
no call recording.

The promise-to-pay flow is modelled — a Tier-3 call can end in a commitment,
which G10 then honours until its date, after which the case either resolves or
reopens. The IVR that would capture that keypress does not exist.

**Why cut:** telephony integration is days of provider onboarding and carrier
approvals, and none of it demonstrates anything about the recovery logic. The
part worth judging — that a voice script is subject to the same validator and
the same gates as an SMS — is built.

### Live mandate re-authorisation

`MANDATE_REPAIR` asks the customer to authorise a new mandate and never retries
against the revoked one. What is missing is the actual UPI Autopay
re-authorisation handshake and the card-network account updater — the link in
the message points at a payment link, not a mandate-creation flow.

**Why cut:** the routing decision and the ladder are the part worth judging;
the handshake is provider integration.

### Real-time streaming — the scheduler, not the decision

This was listed here as cut, with the claim that "the decision path is already
event-shaped, so the change is the scheduler, not the logic". That was an
assertion, and this project's whole position is that assertions are worth less
than things you can run. So the decision half is built:

`POST /api/live/payment-failed` takes a real Razorpay `payment.failed` webhook,
verifies it with the same HMAC-SHA256 scheme against the same webhook secret
Razorpay signs with, and returns the recovery class, the chosen rung and all
eleven gate verdicts in well under a millisecond. It imports `classify`,
`get_next_action` and `evaluate` — the same functions the batch calls — and
adds no decision logic of its own, which is the only reason the demonstration
means anything.

Live decisions are written to a separate hash-chained table, `live_decisions`,
not to the simulation's ledger. The committed evaluation is derived from that
ledger, so a single live decision written there would move the published
numbers the first time anyone tried the webhook.

**Still cut:** the scheduler. The endpoint decides; it does not send, and it
does not own a case over seven days — no follow-up ladder, no cooldown timers
running in real time, no retry queue. Executing means a real message and a
real charge against a real customer, and the frequency and attempt caps are
enforced against a batch's history rather than a merchant's live one.

---

## Known weaknesses in what is built

Listed because they are real, not because they are small.

### The human-review queue cannot be measured yet — and now has somewhere to go

Tier 4 is 89% of total spend for a lift whose confidence interval includes
zero, and an earlier version of this document read that as "not paying for
itself". That is an overreach: `app/core/queue.py` computes it properly and
the honest statement is different.

```
34 treatment cases, 9 control
agent time spent            Rs 1,700
expected incremental        Rs 4,541   (2% marginal lift on Rs 2.27 L)
to detect a 2% lift         387 cases per arm
```

In expectation the lane looks worth it — the expected return exceeds the
spend. What is true is that 34 against 9 cannot distinguish a two-point lift
from nothing. "We cannot tell, and here is what it would take to find out" is
a different and more defensible claim than "it loses money", and the
dashboard's `/queue` page states it that way now.

What *is* independent of sample size: cases below a computed break-even
(`cost ÷ marginal lift` — ₹2,500 at the shipped price) cannot pay back a call
however many of them you have. Six of the thirty-four were below it. That
triage is real and worth doing regardless of what a larger sample would show.

The queue itself was also missing entirely — cases were routed to a person,
billed for their attention, and left with no way to work them or close one.
`/api/queue` and the **Review Queue** page now serve it, with four operator
actions (`APPROVE_CONTACT`, `WRITE_OFF`, `MARK_PAID_OFFLINE`, `HOLD`), each
requiring a named operator and a typed reason, each landing in the same
hash-chained ledger as the agent's own decisions. The rule that matters most:
an operator cannot act on a control-arm case — the call raises rather than
silently no-op'ing, because the measured lift is the difference against those
163 untouched cases, and one worked control case would destroy the experiment
in a way that would be indistinguishable afterwards from the policy having
worked.

This is the finding the per-class table exists to surface, and it points at
our own design — just not the design flaw we first thought it was.

### Six of nine classes are not statistically significant

The aggregate result is significant; most per-lane results are not. Detecting
per-lane effects would need roughly four times the batch.

`MANDATE_REPAIR` is the sharpest case. Arm assignment is stratified per
*cohort* — attempted orders, abandoned carts, invoices — but a recovery class
is only known after classification, so a class that cuts across a cohort takes
whatever control cases it happens to get. Mandate failures land at about n=37
treatment against n=6 control, and the interval is over thirty points wide.
Stratifying by predicted class would fix it and is the obvious next step.

### The receivables lane is measured pessimistically

A seven-day window is short for B2B invoices. Real payment cycles run longer, so
the `RECEIVABLE_CHASE` numbers are probably conservative — including the voice
lift, which is the one we most want to defend.

### The detector is univariate

It scores failure counts per issuer against that issuer's own baseline. It does
not distinguish an issuer-wide outage from one affecting a single payment method
or card network, and it has no notion of expected volume by time of day — a
Sunday 4 AM spike and a Monday 4 PM spike are treated identically.

### Channel selection is consent-driven, not effectiveness-driven

Within a tier, the channel is whichever the customer consented to. It does not
learn that a given segment responds better to WhatsApp than email. A contextual
bandit over channel choice is the obvious next step, and the audit ledger
already records everything it would need to train on.

### One merchant, one dataset, one seed

Every number is from a single synthetic batch. Nothing here has been validated
against another merchant's traffic shape.

---

## What production would need before this touched real customers

1. **Real outcome data.** The oracle would be replaced by actual payment
   webhooks. Every base rate in `docs/assumptions.md` becomes a measurement.
2. **A consent system of record.** Consent is a column here; in production it is
   an audited, timestamped, source-attributed system with its own retention
   rules.
3. **Human review of the first live batch.** The gates should be enforced in
   shadow mode before they are enforced for real.
4. **Per-merchant policy configuration.** The gate constants are global.
   Different merchants have different tolerances, and a fashion retailer's quiet
   hours are not a B2B supplier's.
5. **Rate limiting and idempotency on the executor.** The simulation cannot
   double-send. A production executor with retries can.
6. **Ledger export.** Hash-chained rows in SQLite prove nothing to an external
   auditor. Periodic anchoring to an append-only store outside our control would.
