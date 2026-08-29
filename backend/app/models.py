from sqlalchemy import (
    Column, Integer, String, Boolean, DateTime, Float, JSON, ForeignKey, Index
)
from sqlalchemy.orm import relationship

from app.db import Base


class Customer(Base):
    __tablename__ = "customers"

    customer_id = Column(String, primary_key=True, index=True)
    name = Column(String, nullable=False)
    phone = Column(String, nullable=False)
    email = Column(String, nullable=False)
    language_pref = Column(String, default="hi")  # hi, en, hinglish
    segment = Column(String)                      # new, repeat, vip, b2b
    consent_whatsapp = Column(Boolean, default=False)
    consent_sms = Column(Boolean, default=False)
    consent_email = Column(Boolean, default=False)
    consent_voice = Column(Boolean, default=False)
    opted_out_at = Column(String, nullable=True)  # ISO-8601 UTC
    dnd_registered = Column(Boolean, default=False)
    timezone = Column(String, default="Asia/Kolkata")


class Order(Base):
    __tablename__ = "orders"

    order_id = Column(String, primary_key=True, index=True)
    customer_id = Column(String, ForeignKey("customers.customer_id"), index=True)
    amount_paise = Column(Integer, nullable=False)
    currency = Column(String, default="INR")
    created_at = Column(String)                   # ISO-8601 UTC
    status = Column(String)                       # attempted, paid, abandoned

    # The status this order was seeded with. Re-running a batch has to restore
    # exactly this, not a guess: eight orders are planted as already-settled
    # traps, and inferring "was it paid before?" from the current row silently
    # erases them on the second run. Stored explicitly so the reset is correct
    # by construction rather than by reasoning.
    initial_status = Column(String)

    cart_summary = Column(String)
    arm = Column(String)                          # treatment, control

    # Some customers pay through a completely different route mid-recovery — a
    # second card, the merchant's app, a bank transfer. The agent does not cause
    # it and cannot predict it; it just has to notice and stop. Null for orders
    # where that never happens.
    external_settlement_tick = Column(Integer, nullable=True)

    customer = relationship("Customer")


class Payment(Base):
    __tablename__ = "payments"

    payment_id = Column(String, primary_key=True, index=True)
    order_id = Column(String, ForeignKey("orders.order_id"), index=True)
    customer_id = Column(String, ForeignKey("customers.customer_id"))
    amount_paise = Column(Integer)
    method = Column(String)
    issuer = Column(String, index=True)
    vpa_handle = Column(String, nullable=True)
    card_network = Column(String, nullable=True)
    attempt_no = Column(Integer)
    created_at = Column(String)                   # ISO-8601 UTC

    # Razorpay's own failure taxonomy, kept verbatim. error_source says whose
    # fault it was; error_step says where it broke. Together they decide
    # recoverability — see app/core/classifier.py.
    error_code = Column(String)
    error_source = Column(String)   # customer|business|bank|gateway|internal|NA
    error_step = Column(String)     # payment_initiation|..._authentication|...
    error_reason = Column(String)   # insufficient_funds|issuer_down|...
    error_description = Column(String)


class Invoice(Base):
    __tablename__ = "invoices"

    invoice_id = Column(String, primary_key=True, index=True)
    customer_id = Column(String, ForeignKey("customers.customer_id"), index=True)
    amount_paise = Column(Integer)
    due_date = Column(String)                     # ISO-8601 UTC
    days_overdue = Column(Integer)
    status = Column(String)
    initial_status = Column(String)               # see Order.initial_status
    last_promise_date = Column(String, nullable=True)
    promise_kept = Column(Boolean, default=False)

    customer = relationship("Customer")


class Case(Base):
    __tablename__ = "cases"

    case_id = Column(String, primary_key=True, index=True)
    entity_type = Column(String)                  # order, invoice
    entity_id = Column(String, index=True)
    customer_id = Column(String, ForeignKey("customers.customer_id"), index=True)
    amount_at_risk_paise = Column(Integer)
    recovery_class = Column(String, nullable=True, index=True)
    rule_id = Column(String, nullable=True)       # which classifier rule fired
    state = Column(String, index=True)            # OPEN|PROMISED|RECOVERED|EXHAUSTED|CLOSED
    arm = Column(String, index=True)              # treatment, control
    touches_used = Column(Integer, default=0)
    last_touch_at = Column(String, nullable=True)
    resolution = Column(String, nullable=True)
    resolved_at = Column(String, nullable=True)
    resolved_tick = Column(Integer, nullable=True)
    recovered_paise = Column(Integer, default=0)
    intervention_cost_paise = Column(Integer, default=0)
    promise_date = Column(String, nullable=True)  # from a Tier-3 promise-to-pay
    exception_reason = Column(String, nullable=True)  # why it was never resolved


class Action(Base):
    """
    One row per *attempted* action — including the ones the policy engine
    refused. Blocked attempts are the evidence that the guardrails did
    something, so they are first-class rows, not log lines.
    """
    __tablename__ = "actions"

    action_id = Column(String, primary_key=True, index=True)
    case_id = Column(String, ForeignKey("cases.case_id"), index=True)
    customer_id = Column(String, ForeignKey("customers.customer_id"), index=True)
    tier = Column(Integer)
    channel = Column(String)
    status = Column(String, index=True)           # SENT | BLOCKED
    blocked_by = Column(String, nullable=True, index=True)   # gate id, e.g. "G01"
    gate_decisions_json = Column(JSON)            # full 11-gate trail
    message_body = Column(String, nullable=True)
    llm_used = Column(Boolean, default=False)
    llm_rejected_reason = Column(String, nullable=True)
    cost_paise = Column(Integer, default=0)
    sent_at = Column(String, nullable=True)
    tick = Column(Integer, nullable=True)
    payment_link_url = Column(String, nullable=True)
    payment_link_is_real = Column(Boolean, default=False)


class Event(Base):
    """
    Append-only, hash-chained audit ledger.

    `ts` is a string, not a DateTime, on purpose: the hash is computed over the
    canonical JSON of the row, and SQLite silently drops tzinfo from DateTime
    columns. Storing the exact string we hashed removes an entire class of
    "the chain is broken but nothing was tampered with" bugs.
    """
    __tablename__ = "events"

    event_id = Column(Integer, primary_key=True, autoincrement=True)
    ts = Column(String)                           # ISO-8601 UTC, hashed verbatim
    tick = Column(Integer, nullable=True)
    entity_type = Column(String)
    entity_id = Column(String, index=True)
    actor = Column(String, index=True)
    action = Column(String, index=True)
    decision = Column(String)
    reason_code = Column(String, index=True)
    payload_json = Column(JSON)
    prev_hash = Column(String)
    this_hash = Column(String)


Index("ix_events_entity_ts", Event.entity_id, Event.event_id)


class LiveDecision(Base):
    """
    A decision made on a real webhook rather than on a simulated tick.

    Deliberately a separate table with a separate hash chain. The `events`
    ledger is the simulation's record and the committed evaluation is derived
    from it, so a single live decision written there would move the published
    numbers - the run would stop being reproducible the first time anyone
    demonstrated the webhook.

    Same chaining rules, same verification, different book.
    """

    __tablename__ = "live_decisions"

    decision_id = Column(Integer, primary_key=True, autoincrement=True)
    received_at = Column(String)                  # ISO-8601 UTC, hashed verbatim
    event_id = Column(String, index=True)         # Razorpay's x-razorpay-event-id
    payment_id = Column(String, index=True)
    signature_verified = Column(Boolean)
    recovery_class = Column(String, index=True)
    rule_id = Column(String)
    tier = Column(Integer, nullable=True)
    channel = Column(String, nullable=True)
    allowed = Column(Boolean)
    blocked_by = Column(String, nullable=True, index=True)
    reason_code = Column(String, nullable=True)
    latency_ms = Column(Float)
    payload_json = Column(JSON)
    prev_hash = Column(String)
    this_hash = Column(String)
