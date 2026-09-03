# Guardrails

Eleven gates in `backend/app/core/policy.py`, evaluated in order on every
proposed action. The classifier decides what kind of problem a case is; the
ladder decides the cheapest useful next step; these decide whether that step is
allowed to happen at all.

## The gates

| # | Gate | Rule | Blocked because |
| --- | --- | --- | --- |
| G01 | Consent | Channel consent on file, not opted out, not on DND (voice) | Contacting someone who revoked consent is a regulatory exposure, not a wasted rupee |
| G02 | Quiet hours | No commercial contact 21:00–09:00 IST. Voice only 10:00–19:00 | A 3 AM payment reminder costs more goodwill than the payment is worth |
| G03 | Frequency cap | 1 touch / 24h and 3 / 7 days, **per customer** | Two failed orders from one person is one person |
| G04 | Attempt cap | 3 recovery attempts per case | Past three, more touches buy irritation rather than revenue |
| G05 | Cooldown | 6 hours between touches on the same case | Give the last message time to work before sending another |
| G06 | Amount band | Cost ≤ 15% of the amount at risk, and amount ≥ ₹50 floor | Below the floor, recovery is chased at a loss regardless of channel |
| G07 | Risk hold | `MANUAL_REVIEW` cases reach humans only | The risk engine already said no |
| G08 | Issuer health | Hold silent retries while the issuer is degraded | Retrying into a dead bank burns the case's attempt budget on requests that cannot succeed |
| G09 | Duplicate payment | Stop the moment the order reads `paid` | Chasing someone who already paid risks a double charge and a support ticket |
| G10 | Stopping rule | Terminal states stay terminal; a promise-to-pay is honoured until its date | "Closed" has to mean closed, or none of the other caps mean anything |
| G11 | Ladder order | No tier skipping; voice needs both cheap tiers spent | Voice is five times the cost and far more intrusive — it has to be earned |

## Every gate is evaluated, even after one refuses

The first blocker stops the action, but the full trail is stored on the action
row and rendered as an eleven-cell grid on the case timeline.

"Blocked by consent" is a much weaker artefact than "blocked by consent, and
here is what the other ten gates thought." A compliance reviewer asking why a
customer was not contacted wants the second one.

## Blocks are priced

Each refusal records what it avoided:

- **Spend avoided** — what the message would have cost.
- **Compliance exposure avoided** — ₹500 per consent, DND, quiet-hours,
  frequency or risk-hold violation. A conservative stated figure, not a
  measured one; the point is that the number exists and is defensible, not that
  it is precise.

Guardrails that only ever appear as absences cannot be valued, and anything that
cannot be valued gets cut in the next planning cycle.

## The traps

Every gate has something planted in the dataset for it to catch. A guardrail
that never fires is indistinguishable from one that does not work.

| Trap | Count | Catches |
| --- | --- | --- |
| Customers who revoked consent | 12 | G01 |
| DND-registered numbers | ~10% | G01 (voice) |
| A 40-minute issuer outage straddling the batch start | 45 payments | G08 |
| Orders already settled before the batch | 8 | Classifier R-01 |
| Orders settled out of band **mid-ladder** | 10 | G09 |
| Orders under ₹50 | 15 | G06 |
| Risk-engine blocks | 6 | Classifier R-03, then G07 as backstop |
| Customers already contacted by a legacy system | 3 | G03 |
| Carts abandoned with no payment attempt | 90 | Classifier R-10 (the lane itself) |

The last one is seeded as real `Action` rows at 3 AM and twice in a day —
deliberately non-compliant history, because that is the mess a frequency cap
has to inherit. The compliance tests exclude them: they are input, not output.

## Terminal and transient blocks

A refusal is either something that will clear on its own or something that never
will.

**Transient** — cooldown, quiet hours, frequency cap, degraded issuer,
promise pending. The case stays open and is retried later.

**Terminal** — opted out, DND, below the amount floor, already paid, attempt
budget spent, no consent on any usable channel. The case is closed once with the
reason recorded, and appears in the exception list.

Re-evaluating a terminal refusal on every tick for seven days would produce
eighty identical refusals per case and tell nobody anything.

## Two gates block nothing, and that is the correct result

**G07 (risk hold)** and **G10 (stopping rule)** report zero blocks in the
current run. Not because they are broken — because the ladder never proposes
contact for a risk-blocked case, and terminal cases are filtered before the
gates see them.

They are defence in depth. If either ever fires, there is a bug upstream. They
are reported as zero rather than quietly omitted, because a guardrails page that
only lists the gates that fired is a marketing page.

## Scheduling is not enforcement

The orchestrator parks a refused case for a number of ticks that mirrors the
gate's own rule — a 24-hour frequency cap cannot clear in under twelve two-hour
ticks. This is a performance optimisation and never lets through an action the
gates would have refused.

One deliberate exception: the cooldown parks for two ticks rather than three, so
G05 genuinely refuses the case once and that refusal reaches the audit trail.
Otherwise the scheduler would enforce the rule silently and G05 would look like
dead code.

## The LLM guardrail

Separate from the eleven, in `app/llm/validator.py`. Every model output passes
through it:

1. Valid JSON matching the schema
2. **No literal digits in the body** — placeholders stripped first, so
   `{{amount}}` passes and `1,499` does not
3. `{{amount}}` present; `{{payment_link}}` present except on voice, which
   cannot read out a URL
4. No coercive or legal-threat language, in English and Hindi both — *police*,
   *legal action*, *kanooni*, *adalat*, *vasooli*, *recovery agent*
5. Channel length caps: SMS 160, WhatsApp 700, email 1024, voice 400
6. The model answered for the channel and language it was asked about
7. Voice scripts must disclose that the call is automated and must offer an
   opt-out

A failure at any step falls back to a deterministic template and records the
reason on the action row. Check 2 is the one that makes "the LLM never touches a
rupee" a property of the system rather than a claim about the prompt.
