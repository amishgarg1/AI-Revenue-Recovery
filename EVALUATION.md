# EVALUATION

Every number on this page is produced by `make report` from the committed database. Re-run it and you get this file back — CI asserts exactly that on every push.

Numbers that depend on which services were reachable — how many message bodies the model wrote, how many payment links were minted live — are in [docs/run-environment.md](docs/run-environment.md) instead, because they are a property of the machine that ran the batch rather than of the seed.

## What is measured, and what is simulated

**Real:** the classifier, the eleven-gate policy engine, the escalation ladder, the LLM validator, the hash-chained audit ledger, the treatment/control assignment, and every statistic below.

**Simulated:** whether a customer actually paid. Outcomes come from a seeded oracle whose base rates are documented and justified in `docs/assumptions.md`. The agent has no access to it. No real customer was contacted and no real money moved.

## Headline

| Metric | Value |
| --- | --- |
| Cases in the batch | 815 |
| Observation window | 84 ticks x 2h (7 days) |
| Amount at risk | Rs 11,077,285.00 |
| Treatment arm | 652 cases |
| Control arm (never contacted) | 163 cases |
| Gross recovery, treatment | 33.4% (218/652) |
| Gross recovery, control | 19.0% (31/163) |
| **Net incremental lift** | **+14.4 pp** (95% CI 7.4 to 21.4) |
| Value-weighted lift | +21.1 pp of amount at risk |
| **Incremental amount recovered** | **Rs 1,834,216.61** |
| Intervention spend | Rs 1,908.10 |
| ROI (variable messaging cost only) | 961x |
| Lift needed to break even | 0.022 pp of amount at risk |
| Cost per incremental recovery | Rs 20.30 |

### Is the lift real?

Yes. The 95% confidence interval (7.4 to 21.4 pp) excludes zero, so at n=652 treatment and n=163 control the effect is distinguishable from no effect.

## By recovery class

Aggregate lift can hide a class that outreach is actively hurting.

| Class | Treatment | Control | Lift | 95% CI | Spend |
| --- | --- | --- | --- | --- | --- |
| RECEIVABLE_CHASE | 34.4% (n=64) | 6.2% (n=16) | +28.1 pp | 11.5 to 44.7 | Rs 68.80 |
| RETRY_TIMED | 44.2% (n=163) | 40.0% (n=40) | +4.2 pp | -12.8 to 21.2 | Rs 28.70 |
| AUTO_RETRY | 56.1% (n=98) | 21.1% (n=19) | +35.1 pp | 14.3 to 55.9 | Rs 14.40 |
| SWITCH_METHOD | 18.9% (n=90) | 8.0% (n=25) | +10.9 pp | -2.5 to 24.2 | Rs 32.20 |
| NUDGE_CUSTOMER | 24.4% (n=86) | 16.7% (n=30) | +7.8 pp | -8.4 to 23.9 | Rs 29.20 |
| CHECKOUT_ABANDONED | 29.2% (n=72) | 11.1% (n=18) | +18.1 pp | 0.1 to 36.0 | Rs 19.90 |
| MANUAL_REVIEW | 5.9% (n=34) | 0.0% (n=9) | +5.9 pp | -2.0 to 13.8 | Rs 1,700.00 |
| MANDATE_REPAIR | 21.6% (n=37) | 16.7% (n=6) | +5.0 pp | -27.7 to 37.6 | Rs 14.90 |
| DEAD | 0.0% (n=8) | 0.0% (n=0) | +0.0 pp | 0.0 to 0.0 | Rs 0.00 |

## What the guardrails did

1370 actions were refused, avoiding Rs 410.50 of spend and Rs 583,500.00 of priced compliance exposure.

| Gate | Blocks | Cases | Spend avoided | Compliance avoided |
| --- | --- | --- | --- | --- |
| G01 Consent | 45 | 45 | Rs 22.40 | Rs 12,000.00 |
| G02 Quiet hours | 443 | 420 | Rs 157.40 | Rs 221,500.00 |
| G03 Frequency cap | 700 | 405 | Rs 203.60 | Rs 350,000.00 |
| G04 Attempt cap | 33 | 33 | Rs 6.60 | Rs 0.00 |
| G05 Cooldown | 64 | 64 | Rs 19.20 | Rs 0.00 |
| G06 Amount band | 3 | 3 | Rs 0.90 | Rs 0.00 |
| G07 Risk hold | 0 | 0 | Rs 0.00 | Rs 0.00 |
| G08 Issuer health | 80 | 80 | Rs 0.00 | Rs 0.00 |
| G09 Duplicate payment | 2 | 2 | Rs 0.40 | Rs 0.00 |
| G10 Stopping rule | 0 | 0 | Rs 0.00 | Rs 0.00 |
| G11 Ladder order | 0 | 0 | Rs 0.00 | Rs 0.00 |

G07 (Risk hold), G10 (Stopping rule), G11 (Ladder order) blocked nothing. That is the expected result, not a missing feature: the ladder never proposes the action those gates exist to refuse. They are the backstop that would catch a bug upstream, and if they ever fire there is one.

## Honest exception list

Everything the system did not recover, grouped by why. This is part of the result, not an appendix to it.

| Reason | Cases | Amount left on the table |
| --- | --- | --- |
| Still open when the 7-day observation window closed | 286 | Rs 3,494,906.00 |
| Control arm - observed with no intervention | 132 | Rs 2,050,529.00 |
| No consent on any channel available at tier 2 | 19 | Rs 667,261.00 |
| Number on the national DND registry | 9 | Rs 580,740.00 |
| Escalation ladder complete - no cheaper step left | 57 | Rs 344,046.00 |
| Customer revoked consent | 15 | Rs 303,271.00 |
| Attempt budget exhausted | 33 | Rs 242,939.00 |
| Already settled on another attempt - chasing it would risk a double charge | 8 | Rs 47,616.00 |
| Order was already settled on another attempt | 2 | Rs 17,342.00 |
| No consent on any channel available at tier 1 | 2 | Rs 3,253.00 |
| Amount is below the floor where recovery pays for itself | 3 | Rs 70.00 |

## Audit integrity

- Ledger events: 4185
- Chain valid: **True**
- Broken rows: 0

Every decision above is reconstructable from the ledger. `make verify` recomputes the chain from genesis.

## Limitations

- Outcomes are simulated. The decision logic and the measurement are not, but no claim is made about real-world recovery rates.
- One batch, one seed. The base rates in `docs/assumptions.md` are stated estimates, not measurements from production traffic.
- The control arm is untouched by this system only. In production it would still receive the payment provider's own default retries.
- Voice is scripted and validated end-to-end, but rendered as audio rather than dialled; there is no live telephony integration.
- **The ROI figure counts variable messaging cost only.** It excludes platform, engineering, and support load. Treat it as an upper bound on the unit economics, not as a business case. The break-even line above is the more useful number: it is how small the lift could have been before the campaign stopped paying for its own messages.
- Two lift figures are reported. The case-count lift weights a small cart the same as a large invoice; the value-weighted lift does not. They differ, and both are shown rather than whichever is larger.
