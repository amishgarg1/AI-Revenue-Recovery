# RecoverOS

**Detect. Diagnose. Recover. Prove it.**

Razorpay AI Buildathon — Track 03, AI Revenue Recovery.

A failed payment is not one problem. A bank outage, an empty balance, an
expired card, a lapsed subscription mandate and a risk block all show up as
"payment failed", and the right response to each is different. One of them is
*do nothing*. RecoverOS routes each failure on Razorpay's own error taxonomy,
runs a bounded escalation ladder behind eleven policy gates, and measures what
it actually recovered against a control arm it never touched.

It covers all three lanes in the brief:

| Lane | How it is handled |
| --- | --- |
| **Payment failures** | Routed on `error_source` + `error_step` into silent retry, timed retry, method switch, nudge, mandate repair, human review, or stop |
| **Checkout abandonment** | Its own class: no error to diagnose and nothing to retry, so a shorter two-touch ladder |
| **Overdue receivables** | Email → WhatsApp → Hinglish voice call, with a promise-to-pay hold |

<details>
<summary><strong>The bar, and the example directions, checked off</strong></summary>

**The bar.** *"Show measured money recovered across a batch, with compliant
escalation, stopping rules, and an audit trail."*

| | Where |
| --- | --- |
| Measured money recovered | +14.4 pp against a 163-case control arm, 95% CI 7.4 → 21.4, ₹20.30 per incremental recovery — [EVALUATION.md](EVALUATION.md) |
| Compliant escalation | Eleven gates on every proposed action, all evaluated and all recorded — [docs/guardrails.md](docs/guardrails.md) |
| Stopping rules | G10 closes a case for good and honours a promise-to-pay until its date; `DEAD` spends nothing; attempt and frequency caps bound the rest |
| Audit trail | 4,185 SHA-256 hash-chained events. `make verify` recomputes from genesis; the dashboard can break it and put it back |

**Example directions.** Six of the seven are built. The seventh is a
deliberate no.

| Direction | |
| --- | --- |
| Payment degradation → root cause → recovery action | The classifier routes on `error_source` + `error_step`; the detector z-scores each issuer against its own baseline and holds retries while it is degraded |
| Checkout drop-off recovery | `CHECKOUT_ABANDONED`, its own class with a shorter two-touch ladder — nothing failed, so there is nothing to diagnose or retry |
| Failed-subscription recovery | `MANDATE_REPAIR`. Rule R-04 |
| B2B receivables chaser | `RECEIVABLE_CHASE`: email → WhatsApp → voice, over a seven-day window |
| **Mandate retry sequencer** | **Not built, on purpose.** A retry against a revoked mandate is guaranteed to fail and would spend one of the case's three attempts proving it. The system asks for a fresh authorisation instead. Sequencing retries better was not the answer; not retrying was — [docs/future-scope.md](docs/future-scope.md) |
| Hinglish voice recovery | 23 rendered calls across `en`, `hi` and `hinglish`. Every script clears the same validator: automated-call disclosure, opt-out instruction, no coercive language in English *or* Hindi |
| Promise-to-pay tracker | A Tier-3 call can end in a commitment. G10 then refuses all contact until that date, after which the case resolves or reopens |

</details>

---

## The one architectural rule

> **The LLM never touches a rupee.**

Every amount, every count, every currency figure is computed in Python and SQL.
The model does exactly one job in the money path: it writes a message
*template* containing `{{placeholders}}`. It never sees an amount, never picks a
recipient, and never decides whether to send.

This is enforced mechanically, not by prompt. `app/llm/validator.py` rejects any
draft containing a literal digit. Write "your payment of ₹1,499 is pending" and
the draft is discarded and a deterministic template is used instead. The only
way a rupee figure reaches a customer is Python substituting `{{amount}}` with a
value read from the database.

**You can watch this happen.** The `/validator` page runs the same function the
batch calls against the drafts a model actually produces when told not to write
numbers — an invented rupee figure, an invented due date, a legal threat, a
Hinglish legal threat, a voice script with no opt-out — and shows every check
plus what would really have been sent. It needs no API key.

Two consequences. Templates are cached per (class, tier, language, channel) and
each combination is attempted exactly once, so **688 rendered messages cost 64
provider calls**: eleven messages per call. And when the provider is down,
rate-limits us, or returns malformed JSON, the batch does not stop.

The validator rejects live model drafts on every run: a missing `{{amount}}`
token, a voice script with no opt-out, an SMS one character over the
160-character limit. Each falls back to a deterministic template with the
reason recorded on the action row.

**How many, on the run that produced the committed database, is in
[docs/run-environment.md](docs/run-environment.md).** The figure is not quoted
here on purpose: it depends on which drafts the provider returned and how
often a free tier rate-limited us, so it changes between runs and a number
written into this file would be stale by the next one. The recovery statistics
do not depend on it. A message that fell back to a template recovers exactly
as often as one the model wrote.

---

## Run it

```bash
make demo
```

That seeds the database, runs the batch, and regenerates `EVALUATION.md`. It
needs Python 3.9+ and no API keys. With an empty `.env` the message bodies come
from deterministic templates and payment links are simulated and flagged as
such. **You do not need our credentials to reproduce our numbers.**

```bash
make test      # 299 tests
make verify    # recompute the audit chain from genesis
make webhook   # post a real Razorpay payment.failed at a running API
make api       # backend on :8000
make web       # dashboard on :3000
```

<details>
<summary>Without <code>make</code> (Windows, or a machine with no Make)</summary>

Every target is a one-line script. Set `PYTHONPATH` to `backend` and run them
directly:

```bash
export PYTHONPATH=backend          # PowerShell: $env:PYTHONPATH="backend"

python backend/scripts/seed.py           # build demo.db from seed 42
python backend/scripts/run_batch.py      # run the 7-day simulation
python backend/scripts/make_report.py    # regenerate EVALUATION.md
python backend/scripts/sensitivity.py    # sweep every assumption
python backend/scripts/verify_ledger.py  # recompute the audit chain
python backend/scripts/render_voice.py   # render the voice scripts to audio
python backend/scripts/send_webhook.py   # post a real Razorpay webhook
python -m pytest backend/tests -q        # tests
python -m uvicorn app.main:app --port 8000
cd frontend && npm run dev
```

</details>

`backend/demo.db` is committed and pre-seeded, so a clean clone shows the exact
numbers below without running anything.

---

## Results

Full methodology in **[EVALUATION.md](EVALUATION.md)**, which CI regenerates on
every push and fails if a single figure drifts. Headline:

| | |
| --- | --- |
| Cases | 815 (652 treatment, 163 control) |
| Amount at risk | ₹1.11 Cr |
| Gross recovery, treatment | 33.4% (218/652) |
| Gross recovery, control | 19.0% (31/163) |
| **Net incremental lift** | **+14.4 pp** (95% CI 7.4 → 21.4, significant) |
| Cost per incremental recovery | **₹20.30** |
| Spend | ₹1,908.10 |
| Actions refused by guardrails | 1,370 |
| Audit ledger | 4,185 events, chain valid |

Gross recovery would read 33.4%. But 19.0% of untouched cases came back on
their own, and that share is not ours to claim. Only the difference is.

**Per class, six of the nine lanes cannot be distinguished from zero at this
sample size, and the most expensive lane is not the one carrying the result** —
the human-review queue is 89% of total spend for a lift whose interval includes
zero. That is in `EVALUATION.md` too, because it is the finding, not a
footnote. It is not the same as the lane losing money: in expectation it
looks worth it, and 34 cases against 9 controls simply cannot tell either way.
[docs/future-scope.md](docs/future-scope.md) has the arithmetic, and the
dashboard's **Review Queue** page has the break-even triage that *is*
independent of sample size.

The headline number to argue with is **₹20.30 per incremental recovery**, not
the ROI multiple. The multiple is large because the cost model counts messaging
and nothing else; the per-recovery figure is comparable to something.

---

## What is real and what is simulated

**Real:** the classifier, the eleven-gate policy engine, the escalation ladder,
the issuer-health detector, the LLM validator, the hash-chained audit ledger,
the treatment/control assignment, the statistics, the Razorpay test-mode
Payment Links API integration, the model calls, and the rendered voice audio.

Which of those actually ran on the committed batch, how many bodies the model
wrote and how many payment links were minted live, is recorded in
[docs/run-environment.md](docs/run-environment.md). That file is deliberately
*not* reproducible: it depends on which services answered, and the recovery
statistics do not depend on it at all.

**Simulated:** whether a customer paid. Outcomes come from a seeded oracle whose
base rates are written down and justified in
[docs/assumptions.md](docs/assumptions.md). No decision module imports it. The
classifier, ladder, policy engine and detector cannot see it, so nothing in it
can change what the agent does. The orchestrator calls it only to record what
happened, after it has already acted. No real customer was contacted and no real
money moved.

**How wrong could those numbers be?** [docs/sensitivity.md](docs/sensitivity.md)
moves every one of them across a wide range and reports what the answer does.

Payment links are minted live against Razorpay test mode up to a small budget
and simulated beyond it. Every link is stored with a flag saying which it is,
and the dashboard shows it, so nothing on screen implies more live integration
than there is.

### Point it at your own data

Every case in the batch came from `generate_dataset(seed=42)`, and the fair
objection is that the logic might only work because it wrote its own inputs.
So:

```bash
python backend/scripts/plan.py examples/failed_payments.csv
```

```
243 rows read, 240 usable, 3 rejected      amount column read as rupees
  line 243: amount 'N/A' is not a number

would contact      203 of 240
day-one spend      Rs 786.90              against Rs 36.7 L at risk
REFUSED BY  G06    8   COST_EXCEEDS_BAND x5, BELOW_VIABLE_FLOOR x3
PROJECTED          Rs 4.13 L to Rs 7.62 L
```

Your column names, not ours: `Order ID`, `Amount (INR)` and `Failure Reason`
all resolve, the mapping is reported back, and every rejected row names its
line. **Nothing is stored** - an export is customer data, so it is parsed in
memory and dropped, and no identifier from the file appears anywhere in the
response.

Recovery is a **range**, never a number. We know what we would *do* to your
backlog; we do not know what you would *recover*, because nobody ran the
experiment on your customers. The band is the one
[docs/sensitivity.md](docs/sensitivity.md) establishes.

There is a drag-and-drop version on the dashboard's **Plan a Backlog** page.
Detail in [docs/bring-your-own-data.md](docs/bring-your-own-data.md).

### One engine, many merchants

Quiet hours are 9 PM to 9 AM because that is the Indian norm. A merchant in
another country disagrees before they finish reading it. So the gates enforce
the rules but do not own them. The numbers live in
[`config/policy.yaml`](config/policy.yaml) and resolve per merchant.

```bash
python backend/scripts/send_webhook.py --amount 25000
#   allowed   True

python backend/scripts/send_webhook.py --amount 25000 --merchant merchant_uk_subs
#   allowed   False   blocked by G02
#   BLOCK G06 AMOUNT_BAND   Rs 250.00 is under the Rs 300 floor
```

Same order, same code, different answer, and the refusal explains itself in
that merchant's terms rather than quoting a constant from our source. Deleting
the file is legitimate: the defaults are the values the committed evaluation
was produced with. A *typo* is not: unknown keys are rejected at load, because
a rule you believe you set and did not is worse than no rule.

Detail in [docs/policy.md](docs/policy.md).

### The batch is not the only way in

The fair objection to a simulation is that the logic might only work because a
batch hands it a tidy world. So there is a production-shaped entry point:

```bash
make api                      # in one shell
make webhook                  # in another
```

That posts [`examples/payment_failed.json`](examples/payment_failed.json), a
real Razorpay `payment.failed` envelope — signed the way Razorpay signs it, and
prints the whole decision:

```
  recovery class  SWITCH_METHOD  (rule R-07)
  next action     tier 1 | whatsapp | Rs 0.30
  allowed         False   blocked by G02
  gates run       11
  latency         0.2 ms
  signature       verified=True checked=True
  executed        False

  ok    G01  CONSENT            Consent verified for this channel
  BLOCK G02  QUIET_HOURS        21:00 IST is inside the 9PM-9AM no-contact window
  ok    G03  FREQUENCY_CAP      0 in 24h, 0 in 7d - under cap
  ...
```

Change the failure and the lane changes with it:

```bash
python backend/scripts/send_webhook.py --reason issuer_down
#   AUTO_RETRY    tier 0 | silent | Rs 0.00   — retry quietly, message nobody
python backend/scripts/send_webhook.py --reason payment_blocked_by_risk
#   MANUAL_REVIEW tier 4 | human  | Rs 50.00  — a person, never auto-contacted
python backend/scripts/send_webhook.py --reason refund_issued
#   DEAD          no action                   — the ladder is finished, spend nothing
python backend/scripts/send_webhook.py --forge
#   401 Signature does not match the request body
```

It calls `classify`, `get_next_action` and `evaluate` — the same functions the
batch calls — and adds no decision logic of its own. An unsigned or altered
body is refused with a 401; with no secret configured the decision still runs
but reports `signature_verified: false`, never implying a check that did not
happen.

It decides, it does not send, and its records go to a separate hash-chained
table so the committed evaluation cannot drift. What is still missing is the
scheduler — see [docs/future-scope.md](docs/future-scope.md).

---

## How it works

```
 payments ──▶ detector      z-scores each issuer against its own baseline
                  │
 case ───────▶ classifier   Razorpay's error_source + error_step → recovery class
                  │
              ladder        cheapest useful next step, no tier skipping
                  │
              policy        11 gates, all evaluated, full trail recorded
                  │
              executor      renders the template, mints the link, sends
                  │
              ledger        SHA-256 hash-chained, append-only
```

Details in [ARCHITECTURE.md](ARCHITECTURE.md). The decision table is in
[docs/decision-table.md](docs/decision-table.md); the gates in
[docs/guardrails.md](docs/guardrails.md).

### The agent loop is a simulation, not a single pass

The batch steps through seven simulated days in two-hour ticks against a fixed
clock (`app/core/clock.py`). Nothing in the decision path calls
`datetime.now()`.

That is not decoration. Half the policy engine is time-dependent — quiet hours,
cooldowns, frequency caps, issuer-health windows — and none of it means
anything if every case is processed once, at whatever time the demo happens to
run. An earlier version did exactly that, and four gates were unreachable code
while the results changed depending on the hour you ran it. Same seed, same
clock, same numbers, on any machine, at any hour.

---

## The measurement

- **20% control arm**, assigned by `sha256(order_id + salt) % 100 < 20`. Hashing
  rather than sampling means the arm is a pure function of the id: fixed before
  anything is known about the case, and independently recomputable by anyone
  who wants to check we did not move cases between arms after seeing outcomes.
- **Control cases are classified, measured, and never contacted.** Not once, not
  cheaply, not silently. There is an end-to-end test that fails if a single
  action lands on a control case, because if one does then every number here is
  wrong and nothing else would notice.
- **One random draw per case.** Each delivered touch lowers the bar that draw
  has to clear. Drawing a fresh success roll per touch would give a three-touch
  case three chances against control's one, and the lift would be an artefact
  of the simulation rather than a measurement of the policy.
- **Confidence intervals on everything**, and a null result reported as null,
  with the sample size it would take to detect the effect.
- **Stratified assignment.** Hashing each id gives 20% only in expectation, and
  the 90 abandoned carts landed on 8 controls. Ranking ids by hash within each
  cohort keeps the assignment a pure function of the id while guaranteeing every
  lane a control group worth comparing against.

---

## Limitations

- Outcomes are simulated. No claim is made about real-world recovery rates.
- One batch, one seed. The oracle's base rates are stated estimates, not
  measurements from production traffic.
- The ROI figure counts variable messaging cost only — no platform, engineering
  or support load. It is an upper bound, not a business case. The break-even
  line in `EVALUATION.md` is the more useful number.
- The control arm is untouched *by this system*. In production it would still
  receive the payment provider's own default retries.
- Voice scripts are validated and rendered end to end, but there is no live
  telephony integration. That was a deliberate scope cut — see
  [docs/future-scope.md](docs/future-scope.md).

---

## Repository

```
README.md                  you are here
ARCHITECTURE.md            how the pieces fit, and why the clock holds it up
EVALUATION.md              the numbers — regenerated and checked by CI
2AM.md                     ten real bugs, and how each was found

backend/
  app/
    core/                  the agent
      clock.py             the fixed simulation clock everything else reads
      classifier.py        failure -> recovery class, a decision table
      detector.py          issuer health, z-scored per issuer
      ladder.py            the cheapest useful next step
      policy.py            the eleven gates
      config.py            their numbers, per merchant, from config/policy.yaml
      orchestrator.py      the tick loop
      ledger.py            hash-chained audit trail
      queue.py             the human-review queue and its economics
      operator.py          what a person may do to a case, and the record of it
      live.py              one real webhook, through those same functions
    ingest/                read somebody else's CSV, plan against it
    llm/                   prompts, validator, fallbacks, written-to-spoken
    sim/                   dataset generator, outcome oracle (the agent cannot read it)
    analytics/             experiment statistics, sensitivity sweep, reports
    api/                   FastAPI routers
    models.py  db.py       schema and session
  scripts/                 seed, run-batch, report, verify-ledger, render-voice,
                           send-webhook
  tests/                   299 tests
  demo.db                  committed and pre-seeded, so a clone shows these numbers

config/
  policy.yaml              the gates' numbers, per merchant

examples/
  payment_failed.json      a real Razorpay webhook, for `make webhook`
  failed_payments.csv      a merchant-shaped export, for `make plan`

frontend/src/
  app/                     command centre, live run, cases, case timeline,
                           guardrails, experiment, exceptions, audit, validator
  components/              charts, shared primitives, icons
  lib/                     typed API client, formatting

docs/                      README.md indexes the rest
  data/                    the same results as JSON
scripts/                   start-backend.ps1, for Windows without Make
```

Stack: FastAPI · SQLAlchemy · Pydantic v2 · SQLite · Next.js 16 · TypeScript ·
Tailwind. SQLite because the dataset is synthetic, deterministic and small, and
a single committed file gives a judge the exact numbers with nothing to install.

Full documentation index: [docs/README.md](docs/README.md).
