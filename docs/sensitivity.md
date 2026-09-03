# Sensitivity

`docs/assumptions.md` lists seventy-three numbers we chose rather than
measured. The headline result rests on them, so reporting it as though
it were an observation would be the most misleading thing this project
could do. What we have is not *"+14.4 points"* — it is
*"+14.4 points, if the base rates we picked are right."*

This page moves each of those numbers across a wide range and reports
what happens to the answer. Regenerate it with
`python backend/scripts/sensitivity.py`.

## Why this is a recomputation, not eighty re-runs

No decision module imports the outcome oracle. The classifier, the
ladder, the policy engine and the detector cannot see it, so perturbing
a base rate cannot change which messages were sent — only whether the
customer paid. The actions are held fixed and the outcomes re-decided.

The architectural rule that keeps the experiment honest is the same one
that makes this analysis affordable.

## The committed result

| | |
| --- | --- |
| Net lift | **+14.4 pp** |
| 95% CI | +7.4 → +21.4 |
| Significant | yes |

## What would have to be wrong

The conclusion — a significant positive lift, not the exact figure — survives every assumption tested except these:

| Assumption | Breaks at | In words |
| --- | --- | --- |
| Every marginal lift per rung | ×0.759 | every value would have to be **24% less** than we assumed, all at once |

Every other assumption held across the entire range, ×0.4 to ×2.0.

## Ranked by how much each moves the answer

The first row is the one to attack first. A parameter that swings the
lift by a tenth of a point is not worth arguing about.

| Assumption | Swing | Lift range | Impact |
| --- | --- | --- | --- |
| Every marginal lift per rung | 27.6 pp | +2.3 → +29.9 | material |
| Recovery probability ceiling | 6.3 pp | +8.1 → +14.4 | material |
| Every no-intervention baseline | 6.0 pp | +9.8 → +15.8 | material |
| AUTO_RETRY tier 0 lift | 5.8 pp | +11.2 → +17.0 | material |
| RETRY_TIMED tier 1 lift | 4.3 pp | +12.3 → +16.6 | material |
| RETRY_TIMED tier 0 lift | 4.1 pp | +11.8 → +16.0 | material |
| RETRY_TIMED baseline | 3.4 pp | +13.8 → +17.2 | material |
| SWITCH_METHOD tier 1 lift | 3.2 pp | +12.9 → +16.1 | material |
| AUTO_RETRY baseline | 2.9 pp | +11.5 → +14.4 | material |
| NUDGE_CUSTOMER tier 1 lift | 2.5 pp | +12.9 → +15.3 | material |
| NUDGE_CUSTOMER baseline | 1.5 pp | +13.7 → +15.2 | moderate |
| CHECKOUT_ABANDONED tier 1 lift | 1.4 pp | +13.8 → +15.2 | moderate |
| NUDGE_CUSTOMER tier 2 lift | 1.4 pp | +13.7 → +15.0 | moderate |
| MANDATE_REPAIR tier 1 lift | 1.2 pp | +13.8 → +15.0 | moderate |
| MANDATE_REPAIR tier 2 lift | 1.2 pp | +13.8 → +15.0 | moderate |
| RECEIVABLE_CHASE baseline | 1.2 pp | +13.5 → +14.7 | moderate |
| RECEIVABLE_CHASE tier 1 lift | 1.1 pp | +14.1 → +15.2 | moderate |
| AUTO_RETRY tier 1 lift | 1.1 pp | +14.0 → +15.0 | moderate |
| SWITCH_METHOD baseline | 0.9 pp | +13.5 → +14.4 | moderate |
| RECEIVABLE_CHASE tier 2 lift | 0.9 pp | +14.4 → +15.3 | moderate |
| SWITCH_METHOD tier 2 lift | 0.9 pp | +14.1 → +15.0 | moderate |
| CHECKOUT_ABANDONED baseline | 0.9 pp | +13.5 → +14.4 | moderate |
| RECEIVABLE_CHASE tier 3 lift | 0.8 pp | +14.3 → +15.0 | moderate |
| RETRY_TIMED tier 2 lift | 0.6 pp | +14.3 → +14.9 | moderate |
| MANDATE_REPAIR baseline | 0.5 pp | +14.4 → +14.9 | negligible |
| AUTO_RETRY tier 2 lift | 0.5 pp | +14.3 → +14.7 | negligible |
| CHECKOUT_ABANDONED tier 2 lift | 0.2 pp | +14.3 → +14.4 | negligible |
| DEAD baseline | 0.0 pp | +14.4 → +14.4 | negligible |
| MANUAL_REVIEW baseline | 0.0 pp | +14.4 → +14.4 | negligible |
| MANUAL_REVIEW tier 4 lift | 0.0 pp | +14.4 → +14.4 | negligible |

10 of 30 assumptions move the lift by more than two points. The rest are noise, and saying so is more
useful than defending all seventy-three.

## What this cannot tell you

It varies our assumptions inside our model. If the *shape* of the model
is wrong — if lift is not additive across touches, or if contacting
someone twice annoys them into not paying — no amount of moving these
numbers will show it. That is a limit of simulation, and the only cure
is real outcome data.
