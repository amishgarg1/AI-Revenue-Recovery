"""
Synthetic dataset generator.

Everything here is deterministic: a fixed RNG seed plus the fixed clock in
`app.core.clock`. No `datetime.now()`, no `random` calls outside the seeded
instance. Regenerating on any machine, on any day, produces byte-identical
rows.

The dataset is shaped like real Razorpay traffic — the error taxonomy is theirs
(`error_source` / `error_step` / `error_reason`), not one we invented — and it
carries eight deliberately planted traps. Each exists to make exactly one
guardrail or rule fire during the demo. A guardrail that never fires is a
guardrail nobody believes.
"""

import hashlib
import random
from datetime import timedelta

from app.core.clock import (
    DATA_EPOCH,
    DATA_WINDOW_HOURS,
    BATCH_START,
    SPIKE_START,
    SPIKE_END,
    SPIKE_ISSUER,
    iso,
)

N_CUSTOMERS = 420
N_ORDERS = 600
N_INVOICES = 80

# Carts left before any payment was attempted. These carry no error taxonomy at
# all, which is precisely why they are their own lane: the classifier has
# nothing to route on and the ladder has nothing to retry.
N_ABANDONED_CARTS = 90

CONTROL_PCT = 20
ARM_SALT = "recoveros-v1"

ISSUERS = ["HDFC", "SBI", "ICICI", "Axis", "Kotak"]
UPI_HANDLES = ["@okhdfcbank", "@oksbi", "@okicici", "@okaxis", "@ybl", "@paytm"]

FIRST_NAMES = [
    "Aarav", "Vivaan", "Aditya", "Ananya", "Diya", "Ishaan", "Kavya", "Rohan",
    "Meera", "Arjun", "Sanya", "Kabir", "Riya", "Neel", "Tara", "Yash",
    "Anika", "Devansh", "Isha", "Nikhil",
]
LAST_NAMES = [
    "Sharma", "Verma", "Iyer", "Nair", "Reddy", "Bose", "Kulkarni", "Gupta",
    "Menon", "Chauhan", "Bhatt", "Rao", "Joshi", "Sinha", "Desai", "Pillai",
]

CART_SUMMARIES = [
    "Electronics · 1 item", "Apparel · 3 items", "Groceries · 12 items",
    "Home & Kitchen · 2 items", "Books · 4 items", "Beauty · 2 items",
    "Sports · 1 item", "Subscription · Annual plan",
]

# (error_source, error_step, error_reason, error_code, description)
ERROR_PROFILES = [
    # Weights sum to 1.00. Adding a reason means taking the weight from
    # somewhere, or the tail of the distribution quietly absorbs the remainder.
    (0.32, "bank", "payment_authorization", "insufficient_funds",
     "BAD_REQUEST_ERROR", "Your account has insufficient balance"),
    (0.17, "customer", "payment_authentication", "payment_timeout",
     "GATEWAY_ERROR", "Payment was not completed in time"),
    (0.12, "bank", "payment_authorization", "issuer_down",
     "GATEWAY_ERROR", "Issuing bank is temporarily unavailable"),
    (0.10, "bank", "payment_authorization", "card_declined_by_issuer",
     "BAD_REQUEST_ERROR", "Card declined by the issuing bank"),
    (0.08, "customer", "payment_initiation", "invalid_vpa",
     "BAD_REQUEST_ERROR", "The VPA entered is not valid"),
    (0.06, "internal", "payment_authorization", "payment_blocked_by_risk",
     "BAD_REQUEST_ERROR", "Payment blocked by risk engine"),
    # Subscription failures are ~9% of failed volume for a merchant that sells
    # on auto-pay. Weighted so the lane has enough cases to be measurable at
    # all — at 5% it produced a control arm of five and a confidence interval
    # thirty-eight points wide, which measures nothing.
    (0.06, "customer", "payment_initiation", "mandate_revoked",
     "BAD_REQUEST_ERROR", "The mandate for this subscription was revoked"),
    (0.03, "customer", "payment_initiation", "mandate_expired",
     "BAD_REQUEST_ERROR", "The mandate for this subscription has expired"),
    (0.03, "customer", "payment_authentication", "payment_cancelled",
     "BAD_REQUEST_ERROR", "Payment was cancelled by the customer"),
    (0.03, "gateway", "payment_response", "gateway_technical_error",
     "GATEWAY_ERROR", "Gateway returned a technical error"),
]


def _arm_key(entity_id: str, salt: str = ARM_SALT) -> str:
    return hashlib.sha256((entity_id + salt).encode()).hexdigest()


def assign_arm(entity_id: str, salt: str = ARM_SALT) -> str:
    """
    Deterministic, entity-stable arm assignment for a single id.

    Hashing rather than `random.random()` means the arm is a pure function of
    the id: it survives regeneration, reordering and re-runs, and anyone can
    recompute it independently to check we did not move cases between arms
    after seeing the outcomes.
    """
    return "control" if int(_arm_key(entity_id, salt)[:8], 16) % 100 < CONTROL_PCT \
        else "treatment"


def assign_arms(entity_ids, salt: str = ARM_SALT, control_pct: int = CONTROL_PCT) -> dict:
    """
    Stratified assignment: exactly `control_pct` of *this cohort* held out.

    Hashing each id independently gives 20% only in expectation, and a small
    cohort can land a long way from it. The 90 abandoned carts came out with 8
    controls instead of 18, which left that lane's confidence interval so wide
    it could not say anything — a measurement problem created by the sampling,
    not by the policy.

    Ranking ids by their hash and taking the lowest slice keeps every property
    that mattered: the arm is still a pure function of the id and the salt,
    still fixed before anything is known about a case, and still independently
    recomputable by anyone who wants to check. It just guarantees each lane a
    control group big enough to compare against.
    """
    ids = list(entity_ids)
    ranked = sorted(ids, key=lambda i: _arm_key(i, salt))
    n_control = round(len(ids) * control_pct / 100)
    control = set(ranked[:n_control])
    return {i: ("control" if i in control else "treatment") for i in ids}


def _pick_error(rng: random.Random):
    r = rng.random()
    cum = 0.0
    for weight, src, step, reason, code, desc in ERROR_PROFILES:
        cum += weight
        if r < cum:
            return src, step, reason, code, desc
    last = ERROR_PROFILES[-1]
    return last[1], last[2], last[3], last[4], last[5]


def generate_dataset(seed: int = 42) -> dict:
    rng = random.Random(seed)

    traps = {}

    # ------------------------------------------------------------------ customers
    customers = []
    for i in range(N_CUSTOMERS):
        # Enough b2b accounts that every invoice can belong to a different one.
        # Sharing accounts across invoices sounds more realistic but makes the
        # 7-day frequency cap the binding constraint on the whole receivables
        # lane, so no invoice ever reaches the third rung and the voice tier
        # never runs. One debtor, one invoice keeps the ladder observable.
        segment = rng.choices(
            ["new", "repeat", "vip", "b2b"], weights=[30, 35, 10, 25]
        )[0]
        name = f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}"
        customers.append({
            "customer_id": f"cust_{i:04d}",
            "name": name,
            "phone": f"+9198{rng.randint(10000000, 99999999)}",
            "email": f"{name.split()[0].lower()}.{i}@example.com",
            "language_pref": rng.choices(
                ["hi", "en", "hinglish"], weights=[30, 40, 30]
            )[0],
            "segment": segment,
            "consent_whatsapp": rng.random() > 0.10,
            "consent_sms": rng.random() > 0.05,
            "consent_email": rng.random() > 0.20,
            "consent_voice": rng.random() > 0.30,
            "opted_out_at": None,
            "dnd_registered": rng.random() > 0.90,
            "timezone": "Asia/Kolkata",
        })

    # Trap 1 — customers who have revoked consent. G01 must suppress them.
    for idx in rng.sample(range(N_CUSTOMERS), 12):
        customers[idx]["opted_out_at"] = iso(
            BATCH_START - timedelta(days=rng.randint(1, 30))
        )
    traps["opted_out_customers"] = 12

    b2b_pool = [c for c in customers if c["segment"] == "b2b"] or customers

    # ------------------------------------------------------------------ orders + payments
    orders = []
    payments = []

    for i in range(N_ORDERS):
        cust = rng.choice(customers)
        order_id = f"order_{i:04d}"
        created_at = DATA_EPOCH + timedelta(
            minutes=rng.randint(0, DATA_WINDOW_HOURS * 60 - 1)
        )
        amount = rng.randint(500, 15000) * 100  # paise

        orders.append({
            "order_id": order_id,
            "customer_id": cust["customer_id"],
            "amount_paise": amount,
            "currency": "INR",
            "created_at": iso(created_at),
            "status": "abandoned",
            "cart_summary": rng.choice(CART_SUMMARIES),
            "arm": None,          # stratified per cohort below
            "external_settlement_tick": None,
        })

        attempts = 1
        if rng.random() > 0.70:
            attempts = 2
        if rng.random() > 0.95:
            attempts = 3

        method = rng.choices(["upi", "card", "netbanking"], weights=[55, 35, 10])[0]
        for a in range(attempts):
            src, step, reason, code, desc = _pick_error(rng)
            issuer = rng.choice(ISSUERS)
            pay_time = created_at + timedelta(minutes=a * 7 + rng.randint(0, 4))

            payments.append({
                "payment_id": f"pay_{i:04d}_{a}",
                "order_id": order_id,
                "customer_id": cust["customer_id"],
                "amount_paise": amount,
                "method": method,
                "issuer": issuer,
                "vpa_handle": (
                    cust["phone"][3:] + rng.choice(UPI_HANDLES)
                    if method == "upi" else None
                ),
                "card_network": (
                    rng.choice(["Visa", "MasterCard", "RuPay"])
                    if method == "card" else None
                ),
                "attempt_no": a + 1,
                "created_at": iso(pay_time),
                "error_code": code,
                "error_source": src,
                "error_step": step,
                "error_reason": reason,
                "error_description": desc,
            })

    order_by_id = {o["order_id"]: o for o in orders}
    payments_by_order = {}
    for p in payments:
        payments_by_order.setdefault(p["order_id"], []).append(p)

    # Trap 3 — a 40-minute issuer outage straddling the batch boundary.
    # These are the freshest failures in the dataset, so the detector is still
    # degraded when the first ticks run, and recovers partway through.
    spike_order_ids = []
    for j in range(45):
        order_id = f"order_spike_{j:02d}"
        cust = rng.choice(customers)
        created_at = SPIKE_START + timedelta(
            seconds=rng.randint(0, int((SPIKE_END - SPIKE_START).total_seconds()) - 1)
        )
        amount = rng.randint(800, 12000) * 100
        orders.append({
            "order_id": order_id,
            "customer_id": cust["customer_id"],
            "amount_paise": amount,
            "currency": "INR",
            "created_at": iso(created_at),
            "status": "abandoned",
            "cart_summary": rng.choice(CART_SUMMARIES),
            "arm": None,          # stratified per cohort below
            "external_settlement_tick": None,
        })
        payments.append({
            "payment_id": f"pay_spike_{j:02d}_0",
            "order_id": order_id,
            "customer_id": cust["customer_id"],
            "amount_paise": amount,
            "method": "netbanking",
            "issuer": SPIKE_ISSUER,
            "vpa_handle": None,
            "card_network": None,
            "attempt_no": 1,
            "created_at": iso(created_at),
            "error_code": "GATEWAY_ERROR",
            "error_source": "bank",
            "error_step": "payment_authorization",
            "error_reason": "issuer_down",
            "error_description": "Issuing bank is temporarily unavailable",
        })
        spike_order_ids.append(order_id)
        order_by_id[order_id] = orders[-1]
        payments_by_order[order_id] = [payments[-1]]
    traps["issuer_outage_payments"] = len(spike_order_ids)

    # ------------------------------------------------------------------ abandoned carts
    # Orders with no payment row at all. Smaller baskets than the average
    # attempted order, because the ones people abandon skew toward impulse
    # carts they were never certain about.
    for j in range(N_ABANDONED_CARTS):
        order_id = f"order_cart_{j:03d}"
        cust = rng.choice(customers)
        created_at = DATA_EPOCH + timedelta(
            minutes=rng.randint(0, DATA_WINDOW_HOURS * 60 - 1)
        )
        orders.append({
            "order_id": order_id,
            "customer_id": cust["customer_id"],
            "amount_paise": rng.randint(300, 9000) * 100,
            "currency": "INR",
            "created_at": iso(created_at),
            "status": "abandoned",
            "cart_summary": rng.choice(CART_SUMMARIES),
            "arm": None,          # stratified per cohort below
            "external_settlement_tick": None,
        })
        order_by_id[order_id] = orders[-1]
    traps["abandoned_carts_no_attempt"] = N_ABANDONED_CARTS

    # Three cohorts, each stratified to its own 20% control share: attempted
    # orders, abandoned carts, and (below) invoices. Hashing every id into one
    # pool would let a small cohort drift far from 20% and lose its own
    # comparison.
    attempted_ids = [o["order_id"] for o in orders if o["order_id"].startswith("order_0")
                     or o["order_id"].startswith("order_spike")]
    cart_ids = [o["order_id"] for o in orders if o["order_id"].startswith("order_cart")]
    arms = {**assign_arms(attempted_ids), **assign_arms(cart_ids)}
    for o in orders:
        o["arm"] = arms[o["order_id"]]

    base_order_ids = [f"order_{i:04d}" for i in range(N_ORDERS)]

    # Trap 2 — orders already settled on a later attempt. G09 must stop these
    # before we spend money chasing somebody who already paid us.
    already_paid = rng.sample(base_order_ids, 8)
    for oid in already_paid:
        order_by_id[oid]["status"] = "paid"
    traps["already_paid_orders"] = len(already_paid)

    # Snapshot the seeded status so a re-run can restore it exactly. Without
    # this, resetting has to guess which paid orders were traps and which the
    # agent recovered, and the traps quietly disappear on the second run.
    for order in orders:
        order["initial_status"] = order["status"]

    # Trap 2b — orders that get settled through some other route *while the
    # agent is mid-ladder*. Trap 2 tests whether we notice before starting;
    # this tests whether we notice before the next touch. G09 has to catch it,
    # or we bill somebody twice and chase a customer who already paid.
    settling = rng.sample([o for o in base_order_ids if o not in already_paid], 10)
    for oid in settling:
        order_by_id[oid]["external_settlement_tick"] = rng.randint(4, 55)
    traps["settled_mid_recovery"] = len(settling)

    # Trap 4 — orders so small that any outreach costs more than it can return.
    # G06 must refuse to chase them.
    remaining = [o for o in base_order_ids if o not in already_paid]
    tiny = rng.sample(remaining, 15)
    for oid in tiny:
        amt = rng.randint(10, 49) * 100
        order_by_id[oid]["amount_paise"] = amt
        for p in payments_by_order.get(oid, []):
            p["amount_paise"] = amt
    traps["sub_50_rupee_orders"] = len(tiny)

    # Trap 5 — risk-engine blocks. These must never be auto-contacted (G07).
    remaining = [o for o in remaining if o not in tiny]
    risk_blocked = rng.sample(remaining, 6)
    for oid in risk_blocked:
        for p in payments_by_order.get(oid, []):
            p["error_source"] = "internal"
            p["error_step"] = "payment_authorization"
            p["error_reason"] = "payment_blocked_by_risk"
            p["error_code"] = "BAD_REQUEST_ERROR"
            p["error_description"] = "Payment blocked by risk engine"
    traps["risk_blocked_orders"] = len(risk_blocked)

    # ------------------------------------------------------------------ invoices
    invoices = []
    debtors = (
        rng.sample(b2b_pool, N_INVOICES) if len(b2b_pool) >= N_INVOICES
        else [rng.choice(b2b_pool) for _ in range(N_INVOICES)]
    )
    for i in range(N_INVOICES):
        cust = debtors[i]
        days_overdue = rng.randint(1, 45)
        due_date = BATCH_START - timedelta(days=days_overdue)
        invoices.append({
            "invoice_id": f"inv_{i:03d}",
            "customer_id": cust["customer_id"],
            "amount_paise": rng.randint(5000, 150000) * 100,
            "due_date": iso(due_date),
            "days_overdue": days_overdue,
            "status": "overdue",
            "initial_status": "overdue",
            "last_promise_date": None,
            "promise_kept": False,
        })

    invoice_arms = assign_arms([i["invoice_id"] for i in invoices])

    # ------------------------------------------------------------------ cases
    cases = []
    case_idx = 0
    for o in orders:
        # A paid order still gets a case — the agent has to *discover* that it
        # is already paid and stop. Filtering it out here would be quietly
        # removing the trap we planted.
        cases.append({
            "case_id": f"case_{case_idx:04d}",
            "entity_type": "order",
            "entity_id": o["order_id"],
            "amount_at_risk_paise": o["amount_paise"],
            "recovery_class": None,
            "state": "OPEN",
            "arm": o["arm"],
            "touches_used": 0,
            "last_touch_at": None,
            "resolution": None,
            "resolved_at": None,
            "recovered_paise": 0,
            "intervention_cost_paise": 0,
            "promise_date": None,
            "exception_reason": None,
        })
        case_idx += 1

    for inv in invoices:
        cases.append({
            "case_id": f"case_{case_idx:04d}",
            "entity_type": "invoice",
            "entity_id": inv["invoice_id"],
            "amount_at_risk_paise": inv["amount_paise"],
            "recovery_class": None,
            "state": "OPEN",
            "arm": invoice_arms[inv["invoice_id"]],
            "touches_used": 0,
            "last_touch_at": None,
            "resolution": None,
            "resolved_at": None,
            "recovered_paise": 0,
            "intervention_cost_paise": 0,
            "promise_date": None,
            "exception_reason": None,
        })
        case_idx += 1

    # Trap 6 — customers already contacted recently by *other* systems. Seeded
    # as real prior Action rows rather than a fudged counter, so the frequency
    # cap (G03) reads them the same way it reads its own sends.
    treatment_cases = [c for c in cases if c["arm"] == "treatment"]
    heavy = rng.sample(treatment_cases, 3)
    prior_actions = []
    for n, c in enumerate(heavy):
        entity = c["entity_id"]
        cust_id = (
            order_by_id[entity]["customer_id"]
            if c["entity_type"] == "order"
            else next(i["customer_id"] for i in invoices if i["invoice_id"] == entity)
        )
        for k in range(3):
            prior_actions.append({
                "action_id": f"act_prior_{n}_{k}",
                "case_id": c["case_id"],
                "customer_id": cust_id,
                "tier": 1,
                "channel": "whatsapp",
                "status": "SENT",
                "blocked_by": None,
                "gate_decisions_json": {"note": "pre-existing outreach from a legacy system"},
                "message_body": None,
                "llm_used": False,
                "llm_rejected_reason": None,
                "cost_paise": 30,
                "sent_at": iso(BATCH_START - timedelta(hours=6 + k * 20)),
                "payment_link_url": None,
                "tick": -1,
            })
    traps["pre_touched_customers"] = len(heavy)

    return {
        "customers": customers,
        "orders": orders,
        "payments": payments,
        "invoices": invoices,
        "cases": cases,
        "prior_actions": prior_actions,
        "traps": traps,
    }
