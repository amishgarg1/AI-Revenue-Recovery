# Documentation

Start with [`README.md`](../README.md) at the root, then [`EVALUATION.md`](../EVALUATION.md)
for the numbers. Everything here is the detail behind those two.

## The decisions

| Document | What it answers |
| --- | --- |
| [decision-table.md](decision-table.md) | How a failure becomes a recovery class, and why the rule order is load-bearing |
| [policy.md](policy.md) | The gates' numbers as configuration rather than code, and how one engine serves merchants with different rules |
| [guardrails.md](guardrails.md) | The eleven gates, what each refuses, and the trap planted in the dataset to make it fire |
| [assumptions.md](assumptions.md) | Every number we chose rather than measured — base rates, costs, policy constants — with the reasoning, and the four we are least confident about |

## The results

| Document | What it answers |
| --- | --- |
| [../EVALUATION.md](../EVALUATION.md) | Lift, confidence intervals, per-class breakdown, guardrail value, the honest exception list. **Reproducible** — CI regenerates it on every push and fails if it drifts |
| [future-scope.md](future-scope.md) | What's cut, and the human-review queue's economics computed properly |
| [bring-your-own-data.md](bring-your-own-data.md) | Pointing the policy at a real backlog: a CSV in, a plan out, and why the recovery figure is a range |
| [sensitivity.md](sensitivity.md) | How far the seventy-three chosen numbers can be wrong before the conclusion changes. **Reproducible** — CI regenerates it and fails if it drifts |
| [run-environment.md](run-environment.md) | Message provenance and live payment links. **Not reproducible**, and not meant to be: it depends on which services answered |
| [data/](data/) | The same numbers as JSON, for anything that wants to read them rather than look at them |

## The build

| Document | What it answers |
| --- | --- |
| [../ARCHITECTURE.md](../ARCHITECTURE.md) | How the pieces fit, and why the clock is the thing everything else rests on |
| [../2AM.md](../2AM.md) | Ten real bugs. Most of them produced plausible-looking output while being completely wrong |
| [future-scope.md](future-scope.md) | What was deliberately cut, and the weaknesses in what was kept |
| [video-script.md](video-script.md) | The five-minute walkthrough, timed, written against the committed numbers |

## Diagrams

[diagrams/architecture.svg](diagrams/architecture.svg) — the pipeline, from a failed
payment to a measured outcome.

---

**One thing to know before reading any of it.** The decision logic, the
guardrails, the audit trail and the measurement are real. Whether a customer
paid is simulated by a seeded oracle whose base rates are in
[assumptions.md](assumptions.md). No real customer was contacted and no real
money moved.
