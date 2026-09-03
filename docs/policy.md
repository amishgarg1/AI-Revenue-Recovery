# Policy as configuration

The eleven gates enforce rules. They should not also own them.

Quiet hours are 9 PM to 9 AM because that is the Indian norm. The frequency cap
is one message a day because that felt defensible. A voice call costs ₹1.50
because that is roughly what a call costs. Every one of those is a merchant's
decision, and a merchant in another country will disagree with the first one
before they finish reading it.

So they live in [`config/policy.yaml`](../config/policy.yaml) and the gates read
them from [`app/core/config.py`](../backend/app/core/config.py). **The engine is
the same for everybody; the policy is not.**

---

## The same order, two merchants

Nothing below is a branch in the code. It is one engine reading two policies.

```bash
python backend/scripts/send_webhook.py --amount 25000
#   allowed         True
#   ok    G06  AMOUNT_BAND   Cost is 0.1% of the amount at risk

python backend/scripts/send_webhook.py --amount 25000 --merchant merchant_uk_subs
#   allowed         False   blocked by G02
#   BLOCK G06  AMOUNT_BAND   Rs 250.00 is under the Rs 300 floor
```

A ₹250 order is worth chasing under the default policy and is not worth chasing
for a merchant whose support costs more. The refusal explains itself in that
merchant's terms — the gate reports *their* floor, not a number from our source
code.

---

## What is configurable

| Key | Default | What it decides |
| --- | --- | --- |
| `quiet_start_ist` / `quiet_end_ist` | 21 / 9 | G02 — the no-contact window |
| `voice_start_ist` / `voice_end_ist` | 10 / 19 | G02 — the narrower window for calls |
| `max_touches_per_case` | 3 | G04 — attempts on one case |
| `max_touches_24h` / `max_touches_7d` | 1 / 3 | G03 — contacts per person, across all their cases |
| `cooldown_hours` | 6 | G05 — minimum gap between touches |
| `max_cost_ratio` | 0.15 | G06 — share of the amount at risk we may spend |
| `min_viable_amount_paise` | 5000 | G06 — below this, recovery loses money |
| `compliance_risk_paise` | 50000 | What an avoided consent or DND violation is worth |
| `tier_cost_paise` | 0/30/20/150/5000 | What each rung costs to send |
| `voice_min_amount_paise` | 200000 | Above what a call is worth placing |

What is *not* configurable is which channel each rung uses. Tier 3 is the voice
rung by definition; that is structure, not policy.

---

## Three properties this had to have

### Deleting the file is legitimate

Every value has a default, and the defaults are the values the committed
evaluation was produced with. A deployment with no config reproduces the
published numbers exactly — a test asserts that `config/policy.yaml` has not
drifted from them.

### A file that cannot be trusted fails at load

Not at midnight. A misspelled key is rejected rather than silently ignored,
because a rule a merchant believes they set and did not is worse than no rule.

```yaml
defaults:
  quiet_hours_start: 22        # PolicyConfigError: unknown policy keys
```

So are values that cannot mean anything (`quiet_start_ist: 26`), and
combinations that are individually valid and jointly meaningless:

```yaml
defaults:
  max_touches_24h: 5
  max_touches_7d: 2            # the weekly cap could never bind
```

That last one is the class of mistake that reads fine and quietly disables a
rule.

### A merchant states only what differs

```yaml
merchants:
  merchant_uk_subs:
    quiet_start_ist: 2         # 8:30 PM UK
    cooldown_hours: 24
```

Everything unstated inherits. Repeating a whole policy per merchant is how two
of them silently drift apart six months later.

---

## Resolved once per run, not per gate

The orchestrator resolves the policy when it starts and passes it down through
`ctx`. A policy that changed halfway through a batch would make the audit trail
unreadable — two actions refused by the same gate for different reasons, with
nothing on either row saying the rules moved in between.

`GET /api/policy` serves the resolved policy for every configured merchant, so
a reviewer can see what each one's gates will enforce without reading the code.

---

## What is still missing

The policy is per merchant, not per campaign, and there is no way to change it
without editing a file and restarting. A real deployment would want an
operator-editable surface with its own audit trail — every change recorded with
who made it and why, in the same ledger as the decisions it affects.

That is listed in [future-scope.md](future-scope.md) alongside the scheduler.
