# Bring your own data

Everything else here runs on `generate_dataset(seed=42)`. The fair objection to
that is obvious: the logic might only work because it wrote its own inputs.

So point it at a real backlog.

```bash
python backend/scripts/plan.py examples/failed_payments.csv
```

Or drop a CSV on the **Plan a Backlog** page in the dashboard.

---

## What comes back

```
examples/failed_payments.csv
  243 rows read, 240 usable, 3 rejected
  amount column read as rupees

  COLUMNS MATCHED
    entity_id              <- Order ID
    amount_paise           <- Amount (INR)
    error_reason           <- Failure Reason
    ...

  ROWS REJECTED
    line 242: no id
    line 243: amount 'N/A' is not a number
    line 244: amount is -120000 paise; nothing at risk

  WHAT THE POLICY WOULD DO
    at risk            Rs 3,669,272.18
    would contact      203 of 240
    would not          37 (29 have no useful action at all)
    day-one spend      Rs 786.90

  ROUTED AS
    SWITCH_METHOD          103
    AUTO_RETRY              48
    DEAD                    29
    ...

  REFUSED BY
    G06      8   COST_EXCEEDS_BAND x5, BELOW_VIABLE_FLOOR x3

  PROJECTED INCREMENTAL RECOVERY
    Rs 412,852.39 to Rs 761,519.56
```

Same classifier, same ladder, same eleven gates — imported, not reimplemented.

---

## Three decisions worth defending

### Nothing is stored

A payment export is customer data: names, emails, phone numbers. It is parsed
in memory, planned against, and dropped. The response carries counts and money
and **no row from the file** — a test asserts that no identifier from the input
appears anywhere in the output.

That is not a missing feature. There is no retention question to answer and no
breach surface to defend, and `stored: false` comes back on every response,
because "we deleted it" is worth nothing unless it is stated.

### Recovery is a range, never a number

On a merchant's own data we know what we would **do**. We do not know what they
would **recover** — nobody ran the experiment on their customers.

So the figure is our base rates applied to their volumes, reported across the
band where [our published conclusion still holds](sensitivity.md): roughly a
factor of two. A single confident number on somebody else's data would be the
most dishonest thing this project could print.

### The plan picks its own hour

The gates read the clock. Uploading at midnight would refuse almost everything
on quiet hours and say nothing about the backlog, so the plan is evaluated
inside the merchant's own contact window and reports what is *structurally*
refused: no consent, below the viability floor, risk-blocked, already paid.

The first version used a fixed 11:00 IST. That is inside every window under the
default policy — and inside the *quiet hours* of a merchant in another
timezone, whose plan came back entirely blocked on G02. The hour now comes from
whichever policy is being applied.

---

## Your column names, not ours

Nobody's export happens to use our field names, so common aliases are accepted
and the mapping is reported back. `Order ID`, `order_id`, `Reference ID` and
`Txn ID` all resolve to the same field.

Two details that cost real money if they are wrong:

**Amounts.** A column named for paise is trusted; one named for rupees is
converted; an ambiguous `amount` is decided by whether the value carries
decimals. The unit that was used is reported, because getting it wrong is a
hundredfold error in the headline. Indian digit grouping, a currency symbol and
a trailing minus all parse.

**Header precedence.** An export with both `order_id` and `id` means the first;
a header is claimed by at most one field, so the vaguer column cannot override
the specific one.

An Excel byte-order mark is stripped. Left in place it makes the first header
unmatchable and every row fail for a missing id, which is a baffling error to
debug from the message alone.

---

## Every rejection names its line

"17 rows were invalid" is useless to somebody with a forty-thousand-line
export. Parsing continues past a bad row rather than stopping, because a report
of all forty problems beats forty runs.

A file that cannot be read at all is a different thing from a row that cannot
be used, and the error says which column was missing, which headers *were*
found, and what would have been accepted:

```
Could not find a column for amount_paise.
Headers found: Reference, Reason.
Accepted names for amount_paise: amountpaise, amountinpaise, amountinr, ...
```

---

## What this is not

It is a plan for **day one**, not the seven-day ladder — one touch per case, the
cheapest useful rung. The escalation, the cooldowns and the promise-to-pay holds
are what the batch demonstrates.

And consent is assumed present, because an export does not carry consent state.
G01 would refuse anyone who has opted out or sits on the DND registry, so the
real contactable count is lower than the plan's. The output says so rather than
letting the number stand unqualified.
