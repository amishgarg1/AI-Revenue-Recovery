# 2AM.md

Real bugs from this build, in the order they were found. Several of them were
producing plausible-looking output while being completely wrong, which is the
category worth writing down.

---

## 1. The audit ledger reported tampering that had never happened

**Symptom.** `verify_chain` returned `valid: false` with `broken_at: [1, 2, 3,
4, 5, …]` — every row, from the very first one, on a database nobody had
touched. Two ledger tests failed the same way.

**Cause.** `append()` hashed the event with a timezone-aware
`datetime.isoformat()` (`2026-09-01T10:00:00+00:00`) but stored it in a
SQLAlchemy `DateTime` column. SQLite has no timezone type, so the value comes
back naive, and `verify_chain` re-serialised `2026-09-01T10:00:00` — a
different string, therefore a different hash, on every single row.

**Fix.** `Event.ts` is a `String` holding exactly the ISO-8601 text that went
into the hash. Hash the bytes you store.

**What it cost.** The hash chain is the whole integrity story, and the planned
demo was: verify (valid) → tamper → verify (invalid). It was already invalid
before the tamper, so the demo proved nothing. Worse, a chain that cries wolf
on every row trains you to ignore it. A regression test now writes 25 events,
round-trips them through the database, and asserts the chain survives.

---

## 2. The batch gave different answers depending on what time you ran it

**Symptom.** Two runs of the same seeded dataset, hours apart, produced
different recovery numbers. Nothing was random — `random.seed(42)` everywhere.

**Cause.** The quiet-hours gate compared against `datetime.now()`. Run the demo
at 23:00 IST and G02 blocked every outreach in the batch; run it at 14:00 and it
blocked none. Cooldowns, frequency caps and issuer-health windows had the same
problem.

**Fix.** `app/core/clock.py`. The dataset is generated relative to a fixed
epoch and the batch is a discrete-event simulation over a fixed seven-day
horizon in two-hour ticks. Nothing in the decision path calls `datetime.now()`.

**What it cost.** This was the expensive one, because fixing it meant rewriting
the agent loop. But the loop needed rewriting anyway: it processed each case
exactly once, which meant the escalation ladder never escalated, the voice tier
never ran, and four gates were unreachable code that looked implemented. The
clock and the ladder were the same bug wearing two hats.

---

## 3. Running the tests emptied the committed database

**Symptom.** `demo.db` on disk: 1.8 MB. Tables in it: zero. The API returned
`no such table: cases` from a file that clearly had data in it once.

**Cause.** The test fixtures call `Base.metadata.drop_all()` in teardown, and
`app.db` had one hard-coded path. So the suite was dropping every table in the
demo database — and SQLite does not shrink the file, so it kept its old size and
looked healthy.

**Fix.** `app.db` honours `RECOVEROS_DB_PATH`; `conftest.py` points the suite at
a temp file and asserts it is not the committed one.

**What it cost.** Nearly the whole submission. The failure is invisible locally
— the file is there, the file is big — and only shows up when someone clones the
repo and runs `make demo` against an empty database. That is the worst possible
time to find out.

---

## 4. The measured lift was an artefact of the simulation

**Symptom.** Treatment recovered 47.6%, control 14.3%. A 33-point lift and an
ROI of 1,756×. It looked fantastic and it was nonsense.

**Cause.** The oracle drew an independent success roll after every touch. A case
that got three touches got three chances at recovery; a control case got one.
Most of the "lift" was that arithmetic, not the policy.

**Fix.** One draw per case, fixed at generation time, with each delivered touch
adding a documented *marginal* lift to the probability it has to clear. Both
arms use the same draw, so they differ only by what the interventions added —
which is the quantity the experiment is supposed to measure.

**What it cost.** Nothing yet, but it would have cost the whole project in the
panel. "Why is your lift 33 points when published recovery lifts are in single
digits?" has no good answer. The honest number is +18.8 pp, and the per-class
table now shows that four of six lanes are not significant at this sample size.

---

## 5. Guardrails that could never fire

**Symptom.** Six planted traps in the dataset. Four gates reporting zero blocks.

**Causes**, one per gate:

- **G08 issuer health** — the detector was a module-level singleton that nothing
  ever fed. `is_degraded()` returned `False` for every issuer forever, because
  `record_failure()` was never called.
- **G03 frequency cap** — the orchestrator passed
  `"customer_touches_24h": 0,  # Simplify for simulation`. Hard-coded. The gate
  could not fire under any circumstances.
- **G06 amount band** — the trap was 15 orders under ₹50, but a ₹0.30 WhatsApp
  against a ₹40 order is 0.75% of the amount, far under the 15% cap. The trap
  and the rule did not actually meet. Added a viability floor, on the reasoning
  that the message is not the real cost: a contacted customer replies, and a
  reply costs support time.
- **G09 duplicate payment** — the eight already-paid orders were caught by the
  classifier as `DEAD` before any gate ran, so G09 never saw them. Added a
  second trap: ten orders that get settled out of band *while the agent is
  mid-ladder*, which is the case G09 actually exists for.

**Also found while fixing these:** the receivables ladder ran email (tier 1) →
WhatsApp (tier 1) → voice (tier 3), and G11's no-tier-skipping rule correctly
refused every voice call. Eight blocks, silently, with no voice ever placed.
The gate was right and the ladder was wrong.

**What it cost.** Nothing visible, which is the point — every one of these
looked like working code. A guardrail that never fires is indistinguishable
from a guardrail that does not work, and the only way to tell them apart is to
plant something for it to catch.

---

## 6. Tests that passed in one order and failed in another

**Symptom.** `test_missing_channel_consent_blocks_only_that_channel` failed with
`blocked_by='G08'` — an issuer-health failure in a test that says nothing about
issuers.

**Cause.** The detector singleton again. A detector test loaded an outage into
it, and every test that ran afterwards inherited a degraded HDFC.

**Fix.** An autouse fixture resets it between tests. The suite now passes in any
order.

---

## 7. Running the batch twice killed it

**Symptom.** `python backend/scripts/run_batch.py` on a database that already
had a run in it: `sqlite3.IntegrityError: UNIQUE constraint failed:
actions.action_id`, with a wall of bound parameters and no useful line at the
top.

**Cause.** Action ids are a counter seeded from the rows already present, but
`run_batch.py` never reset anything — it just ran the orchestrator over
whatever cases were still `OPEN`, and collided with the previous run's ids.

**Fix.** `reset_run_state` moved into `app/core/orchestrator.py` and both the
script and the API call it. "Run the batch" means run it, not append to the
last one.

**What it cost.** Nothing yet, and that is the point: it only appears when
somebody presses the button twice, which is precisely what happens during a
demo. The API path already reset; the CLI path did not, because the reset had
been written inside the API router where the script could not see it.

---

## 8. The batch got slower than its own budget

**Symptom.** 113 seconds for a batch that had to finish in under 90. Two new
lanes had added 90 cases — 12% more work for a 180% slowdown.

**Cause.** Profiled rather than guessed: `reset` 0.2s, `prepare` 0.3s, commits
6.6s, ticks 63.8s. Inside the ticks, `GateResult.to_dict` used
`dataclasses.asdict`, which deep-copies recursively. Eleven of those are
serialised for every proposed action across 815 cases and 84 ticks.

**Fix.** A dict literal instead of `asdict`, and the serialised trail reused
for both the action row and the ledger payload instead of being built twice.

**Result.** 113s to 40s, identical output. The slow thing was never the
simulation; it was turning eleven small dataclasses into dictionaries a few
hundred thousand times.

---

## 9. A lane that could not be measured, because of how it was sampled

**Symptom.** `CHECKOUT_ABANDONED` came out at 82 treatment against 8 control.
The confidence interval spanned -11.7 to +37.9 — the lane said nothing.

**Cause.** Arm assignment hashed each id independently, which gives 20% only in
expectation. Ninety carts landed on 8 controls instead of 18. Nothing was wrong
with the policy; the *sampling* had made the lane unmeasurable.

**Fix.** Stratified assignment: rank a cohort's ids by hash and take the lowest
slice. Still a pure function of the id, still fixed before anything is known
about a case, still independently recomputable — but each cohort now gets
exactly its 20%.

**Still not fixed.** Stratification is per cohort — attempted orders, abandoned
carts, invoices — and a recovery *class* is only known after classification. So
`MANDATE_REPAIR` still lands at roughly n=37 against n=6 and is still reported
as not significant. Stratifying by predicted class would fix it. Reported
honestly rather than quoted as though the point estimate meant something.

---

## 10. Two new classes that were invisible in the UI

**Symptom.** `CHECKOUT_ABANDONED` and `MANDATE_REPAIR` rendered as unstyled
pills everywhere, and neither appeared in the case filter — 162 cases you could
not filter to.

**Cause.** The classes were added to the enum, the classifier, the ladder, the
oracle, the templates and the docs. The frontend keeps its own hardcoded list
of class colours and a hardcoded filter list, and neither was on the checklist
because neither is imported from anything.

**Fix.** Both updated, with a comment above the colour map saying why it has to
move in step with the enum.

**What it cost.** Nothing visible in the numbers, which is why it survived a
full run, a report, tests and a push. A hardcoded copy of a backend enum has no
way to fail loudly.

---

## Still open

- **G07 (risk hold) and G10 (stopping rule) block nothing** in the current run.
  That is correct rather than broken: the ladder never proposes contact for a
  risk-blocked case, and terminal cases are filtered before the gates see them.
  They are backstops that would catch a bug upstream. Reported as zero rather
  than quietly hidden, and if either ever fires there is a bug to find.
- **Voice reaches 18 calls out of 80 invoices.** Most invoices exhaust the
  attempt budget or the observation window first. Realistic, but it makes the
  voice lane thin.
- **Python 3.9, not 3.11.** What was on the build machine. Nothing in the code
  requires 3.11, but the README says 3.9+ rather than claiming a version that
  was never tested.
