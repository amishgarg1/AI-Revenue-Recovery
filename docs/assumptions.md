# Assumptions

Everything here is an input we chose. It is written down so the numbers in
`EVALUATION.md` can be argued with rather than taken on trust — disagree with a
figure, change one line in `backend/app/sim/oracle.py`, and re-run.

**The money is simulated.** No real customer was contacted and no real payment
was recovered. What is real is the decision logic, the guardrails, the audit
trail and the measurement method. The oracle exists so those can be evaluated
end to end.

---

## How the outcome model works

Each case gets **one** random draw, fixed at generation time from its case id.
It recovers when its cumulative recovery probability rises above that draw:

```
P(recovery) = baseline(class) + Σ marginal_lift(class, tier) for each touch delivered
              capped at 0.85
```

Both arms use the same draw, so treatment and control differ only by what the
interventions added — which is the quantity the experiment is trying to measure.

**Why not an independent roll per touch?** Because a three-touch case would get
three chances at recovery while a control case got one, and most of the measured
"lift" would be that arithmetic rather than the policy. An earlier version did
exactly this and reported a 33-point lift with an ROI of 1,756×. Both were
artefacts. See [2AM.md](../2AM.md), item 4.

---

## Baseline: recovery with no intervention at all

The probability a customer comes back on their own inside the seven-day window.
This is the number that makes the headline honest — without it, natural recovery
gets credited to the agent.

| Class | Baseline | Reasoning |
| --- | --- | --- |
| `AUTO_RETRY` | 0.29 | The issuer outage ends and a fair share of customers simply try again. |
| `RETRY_TIMED` | 0.24 | Insufficient funds resolves itself at payday for many people, unprompted. |
| `SWITCH_METHOD` | 0.11 | The customer has to work out for themselves that their card is the problem. Few do. |
| `NUDGE_CUSTOMER` | 0.14 | Abandoned checkouts have a real unprompted return rate, driven by intent. |
| `CHECKOUT_ABANDONED` | 0.17 | The highest-intent, lowest-commitment state in the dataset — a meaningful share come back unprompted inside a week. Also the lane where the agent has least to add, because nothing failed. |
| `MANDATE_REPAIR` | 0.04 | Almost nobody re-authorises a lapsed mandate on their own: they either do not notice the subscription stopped, or they meant it to. |
| `RECEIVABLE_CHASE` | 0.09 | B2B invoices do get paid late without chasing, but slowly. |
| `MANUAL_REVIEW` | 0.02 | Risk-blocked payments rarely resolve without a human. |
| `DEAD` | 0.00 | A revoked mandate or a settled order cannot recover again. |

---

## Marginal lift per rung

The *additional* probability each delivered touch contributes.

| Class | Tier | Lift | Reasoning |
| --- | --- | --- | --- |
| `AUTO_RETRY` | 0 | +0.22 | The largest single lift in the model, and the cheapest. The payment failed for reasons that no longer apply; retrying is close to free and frequently just works. |
| `AUTO_RETRY` | 1 | +0.06 | A message adds little once the retry has already failed. |
| `AUTO_RETRY` | 2 | +0.03 | Diminishing. |
| `RETRY_TIMED` | 0 | +0.07 | Retrying an empty account before payday mostly does not help. Deliberately low. |
| `RETRY_TIMED` | 1 | +0.11 | Letting the customer choose the moment is worth more than guessing it. |
| `RETRY_TIMED` | 2 | +0.05 | Diminishing. |
| `SWITCH_METHOD` | 1 | +0.17 | The highest messaging lift in the model: the customer cannot fix a problem nobody has told them about. |
| `SWITCH_METHOD` | 2 | +0.06 | Diminishing. |
| `NUDGE_CUSTOMER` | 1 | +0.10 | A working link removes the friction that caused the drop-off. |
| `NUDGE_CUSTOMER` | 2 | +0.05 | Diminishing. |
| `CHECKOUT_ABANDONED` | 1 | +0.09 | A cart reminder converts, but modestly — they already chose not to finish once and nothing has changed. |
| `CHECKOUT_ABANDONED` | 2 | +0.03 | Diminishing fast; the ladder stops here on purpose. |
| `MANDATE_REPAIR` | 1 | +0.19 | The largest marginal lift in the model and the one the old `DEAD` classification threw away: the customer usually does not know the mandate lapsed, so telling them is most of the work. |
| `MANDATE_REPAIR` | 2 | +0.07 | Diminishing. |
| `RECEIVABLE_CHASE` | 1 | +0.07 | An email reminder is easy for a busy finance team to defer. |
| `RECEIVABLE_CHASE` | 2 | +0.06 | WhatsApp reaches a person rather than an inbox. |
| `RECEIVABLE_CHASE` | 3 | +0.15 | A voice call is the largest lift in the receivables lane, which is why it is the only lane that earns one. |
| `MANUAL_REVIEW` | 4 | +0.02 | Human review recovers very little of what the risk engine blocked — deliberately small, because it is by far the most expensive action in the system and the economics should show that. |

**Ceiling:** 0.85. No amount of contact makes recovery certain.

---

## Promise-to-pay

| Parameter | Value | Reasoning |
| --- | --- | --- |
| Promise rate on an answered voice call | 0.38 | Committing to a date is easy; it costs the debtor nothing at the time. |
| Promise kept | 0.61 | A commitment made aloud to a person is honoured more often than an ignored email, and less often than it is promised. |

A broken promise reopens the case rather than closing it — the customer has not
refused, they have slipped.

---

## Channel costs

Indian merchant rates, and what makes the ROI number mean anything.

| Tier | Channel | Cost |
| --- | --- | --- |
| 0 | Silent gateway retry | ₹0.00 |
| 1 | WhatsApp / email | ₹0.30 |
| 2 | SMS | ₹0.20 |
| 3 | Voice call | ₹1.50 |
| 4 | Human queue | ₹50.00 (agent time) |

**The ROI figure counts these and nothing else.** No platform, engineering or
support load. It is an upper bound on unit economics, not a business case.

---

## Policy constants

| Constant | Value | Reasoning |
| --- | --- | --- |
| Control arm share | 20% | Large enough for a usable interval, small enough that most of the batch is worked. |
| Control assignment | stratified per cohort | Hashing each id independently gives 20% only in expectation. The 90 abandoned carts landed on 8 controls instead of 18, which widened that lane's interval until it said nothing. Ranking ids by hash and taking the lowest slice keeps every property that mattered — a pure function of the id, fixed before anything is known, independently recomputable — and guarantees each cohort a control group worth comparing against. |
| Max attempts per case | 3 | Past three, more touches buy irritation rather than revenue. |
| Frequency cap | 1 / 24h, 3 / 7d per **customer** | Per customer, not per case — two failed orders from one person is one person. |
| Cooldown | 6 hours | Long enough for the previous message to have had a chance. |
| Quiet hours | 21:00–09:00 IST | Standard commercial-messaging practice in India. |
| Voice hours | 10:00–19:00 IST | Narrower, because a call is more intrusive than a message. |
| Max cost ratio | 15% of amount at risk | Above this the recovery is not worth attempting. |
| Viability floor | ₹50 | A ₹0.30 message against a ₹40 order looks cheap, but the message is not the real cost: a contacted customer replies, and a reply costs support time. Fully loaded, a recovery attempt is worth roughly ₹50 of somebody's attention. |
| Voice threshold | ₹2,000 | Below this a ₹1.50 call plus its follow-up handling is not justified. |
| Compliance exposure | ₹500 per avoided violation | A conservative stated figure for pricing what a guardrail protected. Not a measured penalty. |

---

## Detector parameters

| Parameter | Value | Reasoning |
| --- | --- | --- |
| Bucket width | 10 minutes | Short enough to catch a 40-minute outage, long enough that counts are not all zero or one. |
| Z-score threshold | 2.5 | Each issuer is scored against **its own** baseline, so the busiest bank is not permanently "degraded" for being busy. |
| Minimum failures in a bucket | 4 | Stops a quiet issuer's two failures scoring as an infinite z. |
| Degraded tail | 6 hours after the last bad bucket | Recovery is not instantaneous, and flapping in and out of healthy every ten minutes would release retries into a still-broken bank. |
| Counted failures | `issuer_down`, `gateway_technical_error`, `payment_timeout` | A wave of insufficient-funds declines says something about customers, not about the bank's availability. |

---

## Dataset shape

725 cases: 645 orders (600 baseline plus 45 from the planted outage) and 80
invoices, across 420 customers.

Failure-reason mix — roughly the distribution a mid-size Indian merchant sees,
weighted toward UPI:

| Reason | Share |
| --- | --- |
| `insufficient_funds` | 35% |
| `payment_timeout` | 18% |
| `issuer_down` | 12% |
| `card_declined_by_issuer` | 10% |
| `invalid_vpa` | 8% |
| `payment_blocked_by_risk` | 6% |
| `mandate_revoked` | 5% |
| `payment_cancelled` | 3% |
| `gateway_technical_error` | 3% |

Plus eight planted traps — see [guardrails.md](guardrails.md).

---

## What we are least confident about

Named explicitly, because the ones you do not name are the ones you get asked
about.

1. **The `AUTO_RETRY` tier-0 lift of +0.22.** It carries a large share of the
   headline result and it is the number we are least sure of. If real
   post-outage retry success is closer to +0.10, the aggregate lift roughly
   halves.
2. **Control baselines are estimates, not measurements.** They are the
   denominator of the entire result. They came from reasoning about each
   failure mode, not from production data we have access to.
3. **The compliance exposure figure is a placeholder.** ₹500 is defensible as an
   order of magnitude and nothing more. Every "value protected" number inherits
   that uncertainty.
4. **A seven-day window may be short for B2B receivables.** Invoice payment
   cycles run longer, so the receivables lane is probably measured pessimistically.
5. **`MANDATE_REPAIR` is not measurable at this sample size.** Stratification
   balances the three *cohorts* — attempted orders, abandoned carts, invoices —
   but a recovery class is only known after classification, so a class that cuts
   across a cohort still gets whatever control cases it happens to get. Mandate
   failures land at roughly n=37 treatment against n=6 control, and the interval
   is over thirty points wide. The lane's logic is defensible; its lift is not
   measured, and `EVALUATION.md` reports it as not significant rather than
   quoting the point estimate as if it meant something.
