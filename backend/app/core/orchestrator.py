"""
The agent loop.

RecoverOS does not process a case once and stop. It runs a discrete-event
simulation over a seven-day horizon in two-hour ticks, and on every tick it
asks the same question of every open case: what is the cheapest useful thing I
could do right now, and am I allowed to do it?

That structure is what makes the guardrails mean anything. A cooldown only
exists if time passes. A quiet-hours rule only exists if some ticks are at
night. A frequency cap only exists if a customer can be reached twice. An
issuer-health hold only exists if the issuer can recover later and the held
retry can then be released. Processing each case once, at wall-clock "now",
would leave all four as untested code.

Control-arm discipline
----------------------
Control cases are classified, measured, and never touched. They generate no
actions and consume no budget. Their outcomes come from the no-intervention
baseline. If we messaged them, they would not be a control group and the lift
number would be meaningless.
"""

import os
from collections import defaultdict
from datetime import timedelta
from typing import Callable, Optional

from sqlalchemy.orm import Session

from app.core import clock
from app.core.classifier import classify
from app.core.detector import detector
from app.core.ladder import get_next_action, ActionIntent
from app.core import ledger
from app.core.ledger import append
from app.core.policy import evaluate
from app.llm.client import get_message_template, render
from app.models import Action, Case, Customer, Event, Invoice, Order, Payment
from app.razorpay_client.links import build_payment_link
from app.sim import oracle

# Blocks that will never clear on their own. Re-evaluating them every tick for
# seven days would be 80-odd identical refusals per case, so the case is closed
# once with the reason recorded. Everything else is transient and gets retried.
TERMINAL_BLOCK_REASONS = {
    "OPTED_OUT": "Customer revoked consent",
    "DND_REGISTERED": "Number on the national DND registry",
    "COST_EXCEEDS_BAND": "Recovery cost would exceed 15% of the amount at risk",
    "BELOW_VIABLE_FLOOR": "Amount is below the floor where recovery pays for itself",
    "NO_VALUE_AT_RISK": "Nothing recoverable at stake",
    "ALREADY_PAID": "Order was already settled on another attempt",
    "MAX_ATTEMPTS": "Attempt budget exhausted",
    "CASE_CLOSED": "Case already closed",
}

# How long a transient block keeps a case parked, in ticks. These mirror the
# gate's own rule — a 24h frequency cap cannot clear in under 12 two-hour ticks
# — so parking never hides an action the gates would have allowed. Anything not
# listed retries on the next tick.
TRANSIENT_BLOCK_WAIT_TICKS = {
    "COOLDOWN_ACTIVE": 3,     # 6h cooldown
    "FREQ_CAP_24H": 12,       # 24h
    "FREQ_CAP_7D": 12,        # re-check daily; the 7d window slides
    "ISSUER_DEGRADED": 3,     # give the issuer a few hours to come back
    "PROMISE_PENDING": 12,
    "QUIET_HOURS": 1,
    "VOICE_HOURS": 1,
}

# The cooldown is 6h and a tick is 2h, so 3 would be the tight answer. We wake
# a tick early on purpose: the cooldown gate then genuinely refuses the case
# once and that refusal is recorded, instead of the scheduler quietly enforcing
# the rule and leaving G05 looking like dead code in the audit trail.
COOLDOWN_TICKS = 2

PROMISE_WINDOW_DAYS = 3

# How many genuinely live Razorpay test-mode links to mint. Every recovery
# message carries a link; minting six hundred of them against the API would be
# rate-limited noise, so a small subset is real and the rest are marked
# simulated. The README says which is which.
DEFAULT_REAL_LINK_BUDGET = 10


def _row(obj) -> dict:
    return {c.name: getattr(obj, c.name) for c in obj.__table__.columns}


def reset_run_state(db: Session):
    """
    Rewind to the seeded state so a batch can be run again.

    "Run the batch" means run it, not append to whatever the last run left
    behind. Without this, a second `make run-batch` on the same database died
    on a duplicate action id — which is exactly the sort of thing that only
    surfaces when somebody presses the button twice during a demo.

    Only derived rows are cleared. The dataset itself is untouched, so the
    re-run is the same experiment rather than a different one.
    """
    db.query(Event).delete()
    db.query(Action).filter(Action.tick >= 0).delete()

    for case in db.query(Case):
        case.state = "OPEN"
        case.recovery_class = None
        case.rule_id = None
        case.touches_used = 0
        case.last_touch_at = None
        case.resolution = None
        case.resolved_at = None
        case.resolved_tick = None
        case.recovered_paise = 0
        case.intervention_cost_paise = 0
        case.promise_date = None
        case.exception_reason = None

    # Restore every entity to the status it was seeded with. Deriving this from
    # the current row does not work: an order sitting at "paid" might be one of
    # the eight planted already-settled traps, one the agent recovered, or one
    # settled out of band mid-run, and those three want different resets.
    for order in db.query(Order):
        if order.status != order.initial_status:
            order.status = order.initial_status
    for invoice in db.query(Invoice):
        if invoice.status != invoice.initial_status:
            invoice.status = invoice.initial_status

    db.commit()
    ledger.reset_head_cache()


class Orchestrator:
    """
    Runs one full batch. Holds the working set in memory and writes actions and
    ledger events as it goes, committing once per tick.
    """

    def __init__(self, db: Session, emit: Optional[Callable[[dict], None]] = None,
                 real_link_budget: Optional[int] = None,
                 merchant_id: Optional[str] = None):
        self.db = db
        self.emit = emit or (lambda evt: None)

        # Resolved once for the whole run. A policy that changed halfway
        # through a batch would make the audit trail unreadable: two actions
        # refused by the same gate for different reasons, with nothing on
        # either row saying the rules moved in between.
        from app.core import config
        self.merchant_id = merchant_id
        self.policy = config.active(merchant_id)
        self.real_link_budget = (
            DEFAULT_REAL_LINK_BUDGET if real_link_budget is None else real_link_budget
        )
        self.real_links_made = 0

        self.stats = defaultdict(int)
        self.gate_blocks = defaultdict(int)          # reason_code -> count
        self.gate_blocks_by_gate = defaultdict(int)  # gate id -> count
        self.value_protected_paise = 0
        self.compliance_risk_avoided_paise = 0

        self._customers = {}
        self._orders = {}
        self._invoices = {}
        self._payments_by_order = defaultdict(list)
        self._cases = []
        self._customer_touches = defaultdict(list)   # customer_id -> [datetime]
        self._last_tier = {}                         # case_id -> tier
        self._seen_blocks = set()                    # (case_id, gate, reason)
        self._action_seq = 0

        # A case under cooldown, or a customer inside their 24h frequency cap,
        # cannot possibly become actionable for a known number of ticks. Parking
        # them turns 60,000 pointless gate evaluations into a dictionary lookup.
        # It is a scheduling optimisation only: it never lets an action through
        # that the gates would have refused.
        self._wake_at = defaultdict(int)             # case_id -> earliest tick
        self._settling = defaultdict(list)           # tick -> [order_id]
        self._tiers_delivered = defaultdict(tuple)   # case_id -> tiers actually sent

    # ------------------------------------------------------------------ setup
    def prepare(self):
        """Load the working set, wake the detector, classify everything."""
        self._customers = {c.customer_id: _row(c) for c in self.db.query(Customer)}
        self._orders = {o.order_id: o for o in self.db.query(Order)}
        self._invoices = {i.invoice_id: i for i in self.db.query(Invoice)}

        for order in self._orders.values():
            if order.external_settlement_tick is not None:
                self._settling[order.external_settlement_tick].append(order.order_id)

        payments = [_row(p) for p in self.db.query(Payment)]
        for p in payments:
            self._payments_by_order[p["order_id"]].append(p)

        # The detector reads the whole payment history once and derives issuer
        # health windows statistically. Nothing downstream re-derives it.
        detector.load_payments(payments)
        report = detector.health_report(at=clock.BATCH_START)
        degraded = [r["issuer"] for r in report if r["degraded"]]
        append(self.db, ts=clock.iso(clock.BATCH_START), tick=-1,
               entity_type="system", entity_id="detector", actor="detector",
               action="ISSUER_HEALTH_SCAN",
               decision="DEGRADED" if degraded else "ALL_HEALTHY",
               reason_code="Z_SCORE_SPIKE" if degraded else "OK",
               payload={"report": report})
        self.emit({"type": "detector", "degraded": degraded, "report": report})

        # Seed the frequency-cap memory with outreach that happened before this
        # batch existed. A cap that only knows about our own sends is not a cap.
        for a in self.db.query(Action).filter(Action.status == "SENT"):
            if a.customer_id and a.sent_at:
                self._customer_touches[a.customer_id].append(
                    clock.datetime.fromisoformat(a.sent_at)
                )
                self._action_seq += 1

        # Highest amount at risk first. A customer's contact budget is finite —
        # one touch a day, three a week — so within a tick it is a scarce
        # resource, and spending it on a Rs 800 abandoned cart before a
        # Rs 90,000 overdue invoice is simply the wrong allocation. Ordering by
        # case_id would make that allocation an accident of the primary key.
        self._cases = (
            self.db.query(Case)
            .order_by(Case.amount_at_risk_paise.desc(), Case.case_id)
            .all()
        )
        for case in self._cases:
            self._classify_case(case)

        self.db.commit()
        self.stats["cases_total"] = len(self._cases)
        self.emit({"type": "prepared", "cases": len(self._cases)})

    def _entity_for(self, case: Case):
        if case.entity_type == "order":
            return self._orders.get(case.entity_id)
        return self._invoices.get(case.entity_id)

    def _classify_case(self, case: Case):
        entity = self._entity_for(case)
        payments = (
            self._payments_by_order.get(case.entity_id, [])
            if case.entity_type == "order" else []
        )

        facts = {
            "entity_type": case.entity_type,
            "entity_status": getattr(entity, "status", None),
            "days_overdue": getattr(entity, "days_overdue", None),
        }
        result = classify(facts, payments)

        case.recovery_class = result.recovery_class.value
        case.rule_id = result.rule_id
        if case.customer_id is None and entity is not None:
            case.customer_id = entity.customer_id

        append(self.db, ts=clock.iso(clock.BATCH_START), tick=-1,
               entity_type="case", entity_id=case.case_id, actor="classifier",
               action="CLASSIFY", decision=result.recovery_class.value,
               reason_code=result.rule_id, payload=result.rationale_facts)

        # A case that is dead on arrival never enters the loop. Recording why is
        # the difference between "we ignored it" and "we decided about it".
        if result.recovery_class.value == "DEAD":
            case.state = "CLOSED"
            case.resolution = "NOT_RECOVERABLE"
            case.exception_reason = result.rationale_facts.get("why")
            self.stats["closed_dead_on_arrival"] += 1

    # ------------------------------------------------------------------ run
    def run(self) -> dict:
        self.prepare()

        for tick_index, now in clock.ticks():
            touched = self.run_tick(tick_index, now)
            self.db.commit()
            self.emit({
                "type": "tick",
                "tick": tick_index,
                "at": clock.iso(now),
                "ist_hour": clock.ist_hour(now),
                "actions": touched,
                "sent": self.stats["actions_sent"],
                "blocked": self.stats["actions_blocked"],
                "recovered": self.stats["recovered"],
            })

        self._finalise()
        self.db.commit()
        return self.summary()

    def run_tick(self, tick_index: int, now) -> int:
        self._apply_external_settlements(tick_index, now)

        acted = 0
        for case in self._cases:
            if case.state in ("RECOVERED", "EXHAUSTED", "CLOSED"):
                continue
            if tick_index < self._wake_at[case.case_id]:
                continue

            if case.arm == "control":
                if self._resolve_control(case, tick_index, now):
                    acted += 1
                continue

            if self._advance_treatment(case, tick_index, now):
                acted += 1
        return acted

    def _apply_external_settlements(self, tick_index: int, now):
        """
        Mark orders that got paid through some other route this tick.

        The agent does not learn this by being told — it learns it the way a
        real one would, by G09 reading the order status on the next attempt.
        """
        for order_id in self._settling.get(tick_index, ()):
            order = self._orders.get(order_id)
            if order is None or order.status == "paid":
                continue
            order.status = "paid"
            append(self.db, ts=clock.iso(now), tick=tick_index,
                   entity_type="order", entity_id=order_id, actor="payments_feed",
                   action="EXTERNAL_SETTLEMENT", decision="PAID",
                   reason_code="OUT_OF_BAND",
                   payload={"amount_paise": order.amount_paise,
                            "note": "settled outside the recovery flow"})

    # ------------------------------------------------------------------ control
    def _resolve_control(self, case: Case, tick_index: int, now) -> bool:
        """
        Control cases are observed, never touched. The only thing that can
        happen to them is that the customer comes back unprompted.
        """
        if tick_index != oracle.control_resolution_tick(case.case_id, clock.TICK_COUNT):
            return False

        recovered = oracle.determine_outcome(
            case.case_id, case.recovery_class, arm="control"
        )
        if recovered:
            self._mark_recovered(case, tick_index, now, actor="observation",
                                 reason_code="SELF_RECOVERED")
        else:
            case.state = "EXHAUSTED"
            case.resolution = "NO_RECOVERY"
            case.exception_reason = "Control arm - observed with no intervention"
            case.resolved_tick = tick_index
            case.resolved_at = clock.iso(now)
            self.stats["control_not_recovered"] += 1
        return True

    # ------------------------------------------------------------------ treatment
    def _advance_treatment(self, case: Case, tick_index: int, now) -> bool:
        customer = self._customers.get(case.customer_id, {})

        # A promise made on a call is a commitment we honour. Before the date,
        # the case still goes through the full policy evaluation — G10 is what
        # blocks it, so the promise is visible in the audit trail as a decision
        # rather than as an absence. Once the date passes, it resolves.
        if case.state == "PROMISED":
            promise = clock.datetime.fromisoformat(case.promise_date)
            if now < promise:
                return self._blocked_by_promise(case, customer, tick_index, now)
            if oracle.keeps_promise(case.case_id):
                self._mark_recovered(case, tick_index, now, actor="oracle",
                                     reason_code="PROMISE_KEPT")
                self.stats["promises_kept"] += 1
            else:
                case.state = "OPEN"
                self.stats["promises_broken"] += 1
                append(self.db, ts=clock.iso(now), tick=tick_index,
                       entity_type="case", entity_id=case.case_id, actor="orchestrator",
                       action="PROMISE_LAPSED", decision="REOPEN",
                       reason_code="PROMISE_BROKEN",
                       payload={"promised_for": case.promise_date})
            return True

        intent = get_next_action(
            case.recovery_class, case.touches_used, case.amount_at_risk_paise,
            consent_voice=bool(customer.get("consent_voice")),
        )
        if intent is None:
            self._exhaust(case, tick_index, now,
                          "Escalation ladder complete - no cheaper step left")
            return True

        intent = self._pick_channel(intent, customer)

        case_dict = _row(case)
        entity = self._entity_for(case)
        latest_payment = (
            sorted(self._payments_by_order.get(case.entity_id, []),
                   key=lambda p: p.get("attempt_no", 0))[-1]
            if case.entity_type == "order" and self._payments_by_order.get(case.entity_id)
            else None
        )

        ctx = {
            "now": now,
            "tick": tick_index,
            "customer": customer,
            "entity_status": getattr(entity, "status", None),
            "issuer": latest_payment["issuer"] if latest_payment else None,
            "customer_touches_24h": self._touches_within(case.customer_id, now, hours=24),
            "customer_touches_7d": self._touches_within(case.customer_id, now, hours=168),
            "last_tier": self._last_tier.get(case.case_id),
            # Resolved once per evaluation rather than looked up inside each
            # gate, so every gate in one trail is guaranteed to have judged
            # against the same rules.
            "policy": self.policy,
        }

        decision = evaluate(case_dict, intent, ctx)

        if not decision.allowed:
            self._record_block(case, intent, decision, tick_index, now)
            return False

        self._execute(case, intent, decision, ctx, tick_index, now)
        return True

    def _blocked_by_promise(self, case: Case, customer: dict,
                            tick_index: int, now) -> bool:
        """Run the gates anyway so G10's promise hold is recorded once."""
        intent = get_next_action(
            case.recovery_class, case.touches_used, case.amount_at_risk_paise,
            consent_voice=bool(customer.get("consent_voice")),
        )
        if intent is None:
            return False
        decision = evaluate(_row(case), self._pick_channel(intent, customer), {
            "now": now, "tick": tick_index, "customer": customer,
            "entity_status": getattr(self._entity_for(case), "status", None),
            "issuer": None,
            "customer_touches_24h": self._touches_within(case.customer_id, now, 24),
            "customer_touches_7d": self._touches_within(case.customer_id, now, 168),
            "last_tier": self._last_tier.get(case.case_id),
            # Resolved once per evaluation rather than looked up inside each
            # gate, so every gate in one trail is guaranteed to have judged
            # against the same rules.
            "policy": self.policy,
        })
        if not decision.allowed:
            self._record_block(case, intent, decision, tick_index, now)
        return False

    def _pick_channel(self, intent: ActionIntent, customer: dict) -> ActionIntent:
        """
        Within a tier, prefer a channel the customer has actually consented to.
        The ladder chooses how hard to push; this chooses the door to knock on.
        """
        if intent.tier != 1:
            return intent
        for channel in (intent.channel, "whatsapp", "email"):
            if customer.get(f"consent_{channel}"):
                if channel != intent.channel:
                    intent = ActionIntent(intent.tier, channel, intent.cost_paise,
                                          intent.rationale + f" (via {channel}: "
                                          f"only consented channel at this tier)")
                return intent
        return intent

    def _touches_within(self, customer_id: str, now, hours: int) -> int:
        if not customer_id:
            return 0
        cutoff = now - timedelta(hours=hours)
        return sum(1 for t in self._customer_touches[customer_id] if t >= cutoff)

    # ------------------------------------------------------------------ effects
    def _next_action_id(self) -> str:
        self._action_seq += 1
        return f"act_{self._action_seq:06d}"

    def _record_block(self, case: Case, intent: ActionIntent, decision,
                      tick_index: int, now):
        self.stats["gate_evaluations"] += 1
        key = (case.case_id, decision.blocked_by, decision.reason_code)
        first_time = key not in self._seen_blocks

        if first_time:
            # Serialise the trail once and reuse it for both the action row and
            # the ledger payload.
            trail = decision.trail_as_dicts()
            self._seen_blocks.add(key)
            self.stats["actions_blocked"] += 1
            self.gate_blocks[decision.reason_code] += 1
            self.gate_blocks_by_gate[decision.blocked_by] += 1
            self.value_protected_paise += decision.value_protected_paise
            self.compliance_risk_avoided_paise += decision.compliance_risk_avoided_paise

            self.db.add(Action(
                action_id=self._next_action_id(),
                case_id=case.case_id,
                customer_id=case.customer_id,
                tier=intent.tier,
                channel=intent.channel,
                status="BLOCKED",
                blocked_by=decision.blocked_by,
                gate_decisions_json=trail,
                message_body=None,
                cost_paise=0,
                sent_at=None,
                tick=tick_index,
            ))
            append(self.db, ts=clock.iso(now), tick=tick_index,
                   entity_type="case", entity_id=case.case_id, actor="policy_engine",
                   action="GATE_CHECK", decision="BLOCK",
                   reason_code=decision.reason_code,
                   payload={
                       "gate": decision.blocked_by,
                       "tier": intent.tier,
                       "channel": intent.channel,
                       "value_protected_paise": decision.value_protected_paise,
                       "compliance_risk_avoided_paise": decision.compliance_risk_avoided_paise,
                       "trail": trail,
                   })
            self.emit({"type": "blocked", "case": case.case_id,
                       "gate": decision.blocked_by, "reason": decision.reason_code})

        # Transient blocks (cooldown, quiet hours, a degraded issuer) are
        # supposed to clear; the case stays open and tries again later.
        if decision.reason_code in TERMINAL_BLOCK_REASONS:
            self._close_blocked(case, decision, tick_index, now)
        elif decision.reason_code.startswith("NO_CONSENT_"):
            self._close_blocked(case, decision, tick_index, now,
                                f"No consent on any channel available at tier {intent.tier}")
        else:
            self._wake_at[case.case_id] = tick_index + TRANSIENT_BLOCK_WAIT_TICKS.get(
                decision.reason_code, 1
            )

    def _close_blocked(self, case: Case, decision, tick_index, now,
                       override: Optional[str] = None):
        case.state = "CLOSED" if decision.reason_code == "ALREADY_PAID" else "EXHAUSTED"
        case.resolution = "BLOCKED_BY_POLICY"
        case.exception_reason = override or TERMINAL_BLOCK_REASONS.get(
            decision.reason_code, decision.reason_code
        )
        case.resolved_tick = tick_index
        case.resolved_at = clock.iso(now)
        self.stats["closed_by_guardrail"] += 1

    def _execute(self, case: Case, intent: ActionIntent, decision, ctx,
                 tick_index: int, now):
        customer = ctx["customer"]
        language = customer.get("language_pref", "en")

        link_url, link_is_real = self._payment_link(case, customer, intent)

        if intent.channel in ("silent", "human"):
            body, llm_used, llm_rejected = None, False, None
        else:
            template = get_message_template(
                case.recovery_class, intent.tier, intent.channel, language
            )
            body = render(template["body"], {
                "name": customer.get("name", "there"),
                "amount": f"Rs {case.amount_at_risk_paise / 100:,.2f}",
                "payment_link": link_url,
                "merchant": "Demo Merchant",
                "invoice_id": case.entity_id,
                "days": str(getattr(self._entity_for(case), "days_overdue", "") or ""),
            })
            llm_used = template["llm_used"]
            llm_rejected = template["llm_rejected_reason"]
            if llm_rejected:
                self.stats["llm_rejected"] += 1

            append(self.db, ts=clock.iso(now), tick=tick_index,
                   entity_type="case", entity_id=case.case_id, actor="llm",
                   action="DRAFT_MESSAGE",
                   decision="LLM_TEMPLATE" if llm_used else "DETERMINISTIC_FALLBACK",
                   reason_code=llm_rejected or "OK",
                   payload={"language": language, "channel": intent.channel,
                            "validation": template.get("validation"),
                            "template": template["body"]})

        self.db.add(Action(
            action_id=self._next_action_id(),
            case_id=case.case_id,
            customer_id=case.customer_id,
            tier=intent.tier,
            channel=intent.channel,
            status="SENT",
            blocked_by=None,
            gate_decisions_json=decision.trail_as_dicts(),
            message_body=body,
            llm_used=llm_used,
            llm_rejected_reason=llm_rejected,
            cost_paise=intent.cost_paise,
            sent_at=clock.iso(now),
            tick=tick_index,
            payment_link_url=link_url,
            payment_link_is_real=link_is_real,
        ))

        case.touches_used += 1
        case.last_touch_at = clock.iso(now)
        case.intervention_cost_paise += intent.cost_paise
        self._last_tier[case.case_id] = intent.tier
        self._tiers_delivered[case.case_id] += (intent.tier,)
        # The cooldown gate would refuse anything sooner, so do not re-ask.
        self._wake_at[case.case_id] = tick_index + COOLDOWN_TICKS
        if intent.channel not in ("silent", "human"):
            self._customer_touches[case.customer_id].append(now)

        self.stats["actions_sent"] += 1
        self.stats[f"tier_{intent.tier}_sent"] += 1
        self.stats["spend_paise"] += intent.cost_paise

        append(self.db, ts=clock.iso(now), tick=tick_index,
               entity_type="case", entity_id=case.case_id, actor="executor",
               action="SEND", decision="SENT", reason_code=intent.channel.upper(),
               payload={"tier": intent.tier, "cost_paise": intent.cost_paise,
                        "rationale": intent.rationale, "link": link_url,
                        "link_is_real": link_is_real, "body": body})
        self.emit({"type": "sent", "case": case.case_id, "tier": intent.tier,
                   "channel": intent.channel})

        # A Tier-3 voice call can end in a commitment rather than a payment.
        if intent.tier == 3 and oracle.makes_promise(case.case_id, intent.tier):
            promise_date = now + timedelta(days=PROMISE_WINDOW_DAYS)
            case.state = "PROMISED"
            case.promise_date = clock.iso(promise_date)
            self.stats["promises_made"] += 1
            append(self.db, ts=clock.iso(now), tick=tick_index,
                   entity_type="case", entity_id=case.case_id, actor="voice_ivr",
                   action="PROMISE_TO_PAY", decision="PROMISED", reason_code="DTMF_1",
                   payload={"promise_date": case.promise_date})
            return

        recovered = oracle.determine_outcome(
            case.case_id, case.recovery_class,
            self._tiers_delivered[case.case_id], case.arm,
        )
        if recovered:
            self._mark_recovered(case, tick_index, now, actor="oracle",
                                 reason_code="RECOVERED_AFTER_TIER_%d" % intent.tier)

    def _payment_link(self, case: Case, customer: dict, intent: ActionIntent):
        if intent.channel in ("silent", "human"):
            return None, False

        want_real = (
            self.real_links_made < self.real_link_budget
            and os.environ.get("RZP_KEY_ID")
            and os.environ.get("RZP_KEY_SECRET")
        )
        url, is_real = build_payment_link(
            amount_paise=case.amount_at_risk_paise,
            customer=customer,
            reference_id=case.case_id,
            description=f"Recovery for {case.entity_id}",
            recovery_class=case.recovery_class,
            live=bool(want_real),
        )
        if is_real:
            self.real_links_made += 1
        return url, is_real

    def _mark_recovered(self, case: Case, tick_index, now, actor: str, reason_code: str):
        case.state = "RECOVERED"
        case.resolution = "RECOVERED"
        case.resolved_at = clock.iso(now)
        case.resolved_tick = tick_index
        case.recovered_paise = case.amount_at_risk_paise
        entity = self._entity_for(case)
        if entity is not None and hasattr(entity, "status"):
            entity.status = "paid"
        self.stats["recovered"] += 1
        self.stats["recovered_paise"] += case.amount_at_risk_paise
        append(self.db, ts=clock.iso(now), tick=tick_index,
               entity_type="case", entity_id=case.case_id, actor=actor,
               action="OUTCOME", decision="RECOVERED", reason_code=reason_code,
               payload={"amount_paise": case.amount_at_risk_paise,
                        "touches_used": case.touches_used,
                        "spend_paise": case.intervention_cost_paise})
        self.emit({"type": "recovered", "case": case.case_id,
                   "amount_paise": case.amount_at_risk_paise})

    def _exhaust(self, case: Case, tick_index, now, reason: str):
        case.state = "EXHAUSTED"
        case.resolution = "NO_RECOVERY"
        case.exception_reason = reason
        case.resolved_tick = tick_index
        case.resolved_at = clock.iso(now)
        self.stats["exhausted"] += 1
        append(self.db, ts=clock.iso(now), tick=tick_index,
               entity_type="case", entity_id=case.case_id, actor="orchestrator",
               action="STOP", decision="EXHAUSTED", reason_code="LADDER_COMPLETE",
               payload={"reason": reason, "touches_used": case.touches_used})

    def _finalise(self):
        """Anything still open when the horizon ends is an honest exception."""
        end = clock.BATCH_END
        for case in self._cases:
            if case.state in ("OPEN", "PROMISED"):
                case.state = "EXHAUSTED"
                case.resolution = "NO_RECOVERY"
                case.exception_reason = (
                    case.exception_reason
                    or "Still open when the 7-day observation window closed"
                )
                case.resolved_at = clock.iso(end)
                case.resolved_tick = clock.TICK_COUNT
                self.stats["open_at_horizon"] += 1

        append(self.db, ts=clock.iso(end), tick=clock.TICK_COUNT,
               entity_type="system", entity_id="batch", actor="orchestrator",
               action="BATCH_COMPLETE", decision="DONE", reason_code="HORIZON_REACHED",
               payload=dict(self.stats))

    # ------------------------------------------------------------------ output
    def summary(self) -> dict:
        return {
            "stats": dict(self.stats),
            "gate_blocks": dict(self.gate_blocks),
            "gate_blocks_by_gate": dict(self.gate_blocks_by_gate),
            "value_protected_paise": self.value_protected_paise,
            "compliance_risk_avoided_paise": self.compliance_risk_avoided_paise,
            "real_payment_links": self.real_links_made,
            "ticks": clock.TICK_COUNT,
            "horizon_hours": clock.HORIZON_HOURS,
        }

    # Kept so older scripts and the API keep working.
    def run_batch(self) -> dict:
        return self.run()
