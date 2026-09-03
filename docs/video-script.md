# Five-minute video script

Every number below was checked against the running API on the committed
database. If you re-run the batch they will still be these numbers — that is
the point of the fixed clock.

**Setup:** OBS, screen capture, no face cam needed. Backend and frontend both
running, `/api/health` hit once beforehand so nothing is cold. Three takes; the
first one is always bad.

**Rule for the whole recording:** show the product, never a slide. Never say "I
would have" — only what exists.

**One thing you must not say:** that the recovery outcomes are live. Whether a
customer paid is simulated by a seeded oracle. The decision logic, the
guardrails, the audit trail and the measurement are real, and saying exactly
that is stronger than being caught overclaiming.

---

## 0:00–0:25 · The problem, with a number

**On screen:** `/` Command Center. Let the hero figure sit for a beat, then
scroll to the divergence chart and stop there.

> "Eight hundred and fifteen cases — failed payments, abandoned carts and
> overdue invoices. One crore eleven lakh rupees at risk.
>
> This is the chart the whole project is about. The blue line is the cases the
> agent worked. The grey one is a fifth of the batch it was never allowed to
> touch. The wedge between them is the only thing we're allowed to take credit
> for — and the dark vertical stripes are the seven nights, where the
> quiet-hours gate suppresses everything and the blue line goes flat."

Do not rush this. Hovering the chart at day 3 to show the tooltip is worth two
seconds.

---

## 0:25–0:52 · The architecture rule

**On screen:** `docs/diagrams/architecture.svg`, or the ARCHITECTURE.md section.

> "One rule runs through all of it: the LLM never touches a rupee.
>
> Classification is a decision table on Razorpay's own error taxonomy — no
> model. Amounts are computed in Python. Eleven policy gates decide whether
> anything is allowed to happen. The model does exactly one job: it writes a
> message template with placeholders. And a validator rejects any draft
> containing a literal digit, so the only way a rupee figure reaches a customer
> is Python substituting it from the database.
>
> Six hundred and eighty-eight messages, sixty-four model calls — each
> combination of class, tier, language and channel is asked once and cached."

---

## 0:52–1:55 · The live run

**On screen:** `/run`. Press **Run batch**. Talk over the stream.

> "Seven simulated days in two-hour ticks. The clock is fixed — nothing here
> calls `datetime.now()`, so this produces identical numbers on any machine at
> any hour.
>
> The detector has already flagged HDFC as degraded — it z-scores each issuer
> against its own baseline, so a busy bank isn't mistaken for a broken one.
> Retries against it are being *held*, not spent.
>
> Watch the gates fire." *(point at the Gates Firing panel as bars grow)*
>
> "Quiet hours — nothing goes out at night. Frequency cap — this customer has
> already been contacted today, across all their cases, so we wait. Cooldown.
> Attempt cap. And here" *(scroll the feed)* "an order that was settled through
> another route while we were mid-ladder — we stop, because chasing someone who
> already paid is a double charge and a support ticket."

Let it reach roughly tick 40 before moving on.

---

## 1:55–2:28 · One case, all the way down

**On screen:** `/cases`, open **`case_0797`** — a `RECEIVABLE_CHASE` case with
seven actions that reaches the Tier-3 voice call.

> "One case. This is the Razorpay failure taxonomy the routing was built on —
> `error_source` says whose fault it was, `error_step` says where it broke.
>
> Then every action, with all eleven gate verdicts, not just the one that
> blocked. A compliance reviewer asking why this customer wasn't contacted
> doesn't want 'blocked by consent' — they want to see what the other ten gates
> thought.
>
> Here's the Hinglish voice script, with the amount substituted by Python."
> *(play the audio for three or four seconds)* "That recording is this case's
> own call — the name and the amount you can read on screen are the name and
> the amount you just heard. And underneath, the raw ledger, every row
> hash-chained to the one before it."

---

## 2:28–2:50 · The claim, running

**On screen:** `/validator`. Pick **"The model wrote the rupee figure itself"**.

> "The architecture rests on one claim, so here it is running rather than
> asserted. This is a draft a model actually produces when you tell it not to
> write numbers — it wrote 'Rs 1,499'. That number is the model's guess, not the
> database's value.
>
> Rejected. No literal digits in the body — failed. And here's what goes out
> instead: the deterministic template, rendered with a real case's figures —
> it even tells you which case, so you can go and check."

The rendered preview reads **Vivaan Menon, Rs 8,317.00, from `case_0000`**. Do
not quote a rupee figure from memory here — read what is on the screen.

---

## 2:50–3:08 · Break the audit trail, then put it back

**On screen:** `/audit`.

> "Four thousand one hundred and eighty-five events, chain valid.
>
> Now watch." *(click **Tamper with a record**)*
>
> "I've rewritten one recorded amount, the way somebody covering their tracks
> would. Nothing else touched." *(page updates)* "Broken — and it names the row.
>
> And back." *(click **Restore the record**)* "Same bytes, same hash. The
> detection is derived from the content, not from a flag saying somebody edited
> it."

---

## 3:08–3:38 · It is not only a simulation

**On screen:** a terminal beside the browser. `make api` is already running;
type `make webhook`.

> "Fair question at this point: does any of this work outside a batch that
> hands it a tidy world?
>
> That's a real Razorpay `payment.failed` webhook, signed the way Razorpay
> signs it. Same classifier, same ladder, same eleven gates — the live handler
> imports those functions, it doesn't reimplement them. Two tenths of a
> millisecond.
>
> Card declined by the issuer, so: switch method. Blocked, because it's inside
> the quiet-hours window."

Then run one or two of these — this is the strongest thirty seconds for a
payments audience:

```bash
python backend/scripts/send_webhook.py --reason issuer_down
#   AUTO_RETRY    tier 0 | silent | Rs 0.00   — retry quietly, message nobody
python backend/scripts/send_webhook.py --reason payment_blocked_by_risk
#   MANUAL_REVIEW tier 4 | human  | Rs 50.00  — a person, never auto-contacted
python backend/scripts/send_webhook.py --forge
#   401 Signature does not match the request body
```

> "Bank outage: retry silently, message nobody. Risk block: a person, never
> auto-contacted. And a webhook nobody signed doesn't get in."

---

## 3:38–3:55 · What the guardrails refused

**On screen:** `/guardrails`.

> "One thousand three hundred and seventy actions refused, and every refusal
> carries its full eleven-gate trail.
>
> Three of the eleven gates blocked nothing at all — risk hold, the stopping
> rule and ladder order. That's correct, not missing: they're backstops, and
> the ladder never proposes the thing they exist to prevent. If one of them
> ever fires, I have a bug upstream — and I'd rather report the zero than hide
> it."

---

## 3:55–4:35 · Did it work?

**On screen:** `/experiment`.

> "The real question. Twenty percent of cases were held out and never
> contacted — assigned by hashing the order id, so the arm was fixed before
> anything was known about the case, and anyone can recompute it.
>
> Treatment recovered thirty-three point four percent. Control — untouched —
> nineteen. So the gross number is thirty-three, but nineteen of that would
> have happened anyway. **Net incremental lift, fourteen point four percentage
> points**, confidence interval seven point four to twenty-one point four. It
> excludes zero, so it's real at this sample size.
>
> Twenty rupees thirty per incremental recovery. I'm quoting that rather than
> the ROI multiple, because the multiple only counts messaging cost and the
> per-recovery figure is comparable to something.
>
> And now the part I'd rather you saw from me than found yourselves."
> *(scroll to the per-class table)*
> "**Six of these nine lanes are not statistically significant.** And the most
> expensive lane — the human review queue, seventeen hundred rupees,
> eighty-nine percent of my total spend — has a confidence interval that
> includes zero. That's not the same as losing money: in expectation it looks
> worth it, and thirty-four cases against nine controls simply can't tell
> either way. So I built it a break-even instead — below two thousand five
> hundred rupees, a call can't pay for itself no matter how big the sample
> gets, and that's the triage that doesn't need more data. That's a finding
> about my own design, and it's in EVALUATION.md."

---

## 4:35–5:00 · What broke, and what's honest

**On screen:** `2AM.md`, scrolling.

> "Ten real bugs, and almost every one produced plausible-looking output while
> being completely wrong. The audit ledger reported tampering that never
> happened, because it hashed a timezone-aware timestamp and stored a naive
> one. The batch gave different answers depending on what time of day you ran
> it. The test suite was quietly emptying the committed database. And the
> measured lift was thirty-three points until I noticed the oracle was giving
> treatment three chances at recovery and control one.
>
> One thing to be clear about: whether a customer paid is simulated, by a
> seeded oracle whose base rates are written down. The routing, the guardrails,
> the ledger and the statistics are real.
>
> `make demo` runs the whole thing from a clean clone. No API keys. Same
> numbers. Thank you."

---

## Timing checks

| Segment | Ends at |
| --- | --- |
| Problem | 0:25 |
| Architecture rule | 0:52 |
| Live run | 1:55 |
| One case | 2:28 |
| Validator running | 2:50 |
| Audit tamper + restore | 3:08 |
| Live webhook | 3:38 |
| Guardrails | 3:55 |
| Experiment | 4:35 |
| 2AM + close | 5:00 |

**Hard stop at 5:00.** A 5:30 video gets cut, and the cut lands in the middle of
the honest-metrics segment, which is the part that wins the track.

## If you have to lose thirty seconds

Drop the guardrails segment entirely — the gates are already visible firing
during the live run. Do not cut the per-class honesty in the experiment
segment, and do not cut the webhook: those are the two strongest half-minutes
in the video.

## Before you record

- [ ] `make demo` on a clean clone, so the numbers on screen match EVALUATION.md
- [ ] Hit `/api/health` once to warm the backend
- [ ] `make api` running in a second shell, with `RZP_WEBHOOK_SECRET` set, so
      `make webhook` shows `verified=True` rather than "no secret configured"
- [ ] Have `case_0797` open in a tab — Tier-3 voice script, its own rendered
      audio, and the promise-to-pay hold firing on the two calls after it
- [ ] Have a live-link case open: `case_0045`, `case_0206`, `case_0478` and
      `case_0731` each carry a real Razorpay test-mode `short_url`
- [ ] Open `/validator` once so it is warm, with the rupee-figure sample selected
- [ ] After the tamper demo, click **Restore the record** — there is no need to
      re-run the batch any more
- [ ] After recording: `git checkout backend/demo.db`. SQLite rewrites pages, so
      the file shows as modified even when its contents are identical
