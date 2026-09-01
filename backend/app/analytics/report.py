"""
Turn a finished batch into the numbers that go in EVALUATION.md, the dashboard,
and the video — computed in exactly one place so those three can never disagree.
"""

from collections import defaultdict
from typing import Dict, List

from sqlalchemy.orm import Session

from app.analytics.experiment import (
    calculate_experiment_results, exception_report, per_class_breakdown,
)
from app.core import clock
from app.core.detector import detector
from app.core.ledger import verify_chain
from app.core import config
from app.models import Action, Case, Event

GATE_NAMES = {
    "G01": "Consent", "G02": "Quiet hours", "G03": "Frequency cap",
    "G04": "Attempt cap", "G05": "Cooldown", "G06": "Amount band",
    "G07": "Risk hold", "G08": "Issuer health", "G09": "Duplicate payment",
    "G10": "Stopping rule", "G11": "Ladder order",
}

# Blocks that avoid a regulatory or reputational exposure rather than a rupee
# of spend. Mirrors app/core/policy.COMPLIANCE_REASONS.
COMPLIANCE_REASONS = {"OPTED_OUT", "DND_REGISTERED", "QUIET_HOURS", "VOICE_HOURS",
                      "FREQ_CAP_24H", "FREQ_CAP_7D", "RISK_HOLD"}


def _case_dicts(db: Session) -> List[dict]:
    return [
        {c.name: getattr(case, c.name) for c in case.__table__.columns}
        for case in db.query(Case)
    ]


def guardrail_report(db: Session) -> Dict:
    """
    What the guardrails actually did, in money.

    Every gate is listed, including the ones that never fired. A gate reporting
    zero blocks is information: it means nothing upstream ever proposed the
    thing it exists to prevent.
    """
    per_gate = defaultdict(lambda: {
        "gate": "", "name": "", "blocks": 0, "cases": set(),
        "spend_avoided_paise": 0, "compliance_avoided_paise": 0,
        "reasons": defaultdict(int),
    })

    for action in db.query(Action).filter(Action.status == "BLOCKED"):
        gate = action.blocked_by or "UNKNOWN"
        row = per_gate[gate]
        row["gate"] = gate
        row["name"] = GATE_NAMES.get(gate, gate)
        row["blocks"] += 1
        row["cases"].add(action.case_id)

        reason = next(
            (g["reason_code"] for g in (action.gate_decisions_json or [])
             if not g.get("allowed")),
            "UNKNOWN",
        )
        row["reasons"][reason] += 1

        # What the blocked action would have cost had it gone out.
        from app.core.ladder import TIER_SPEC
        would_have_cost = TIER_SPEC.get(action.tier, ("", 0))[1]
        row["spend_avoided_paise"] += would_have_cost
        if reason in COMPLIANCE_REASONS:
            row["compliance_avoided_paise"] += config.active().compliance_risk_paise

    rows = []
    for gate in sorted(set(GATE_NAMES) | set(per_gate)):
        row = per_gate.get(gate)
        if row is None:
            rows.append({
                "gate": gate, "name": GATE_NAMES.get(gate, gate), "blocks": 0,
                "cases_affected": 0, "spend_avoided_paise": 0,
                "compliance_avoided_paise": 0, "reasons": {},
            })
            continue
        rows.append({
            "gate": gate,
            "name": row["name"],
            "blocks": row["blocks"],
            "cases_affected": len(row["cases"]),
            "spend_avoided_paise": row["spend_avoided_paise"],
            "compliance_avoided_paise": row["compliance_avoided_paise"],
            "reasons": dict(row["reasons"]),
        })

    return {
        "gates": rows,
        "total_blocks": sum(r["blocks"] for r in rows),
        "total_spend_avoided_paise": sum(r["spend_avoided_paise"] for r in rows),
        "total_compliance_avoided_paise": sum(
            r["compliance_avoided_paise"] for r in rows
        ),
    }


def delivery_report(db: Session) -> Dict:
    """Sends by tier and channel, plus how the message bodies were produced."""
    by_tier = defaultdict(lambda: {"sent": 0, "spend_paise": 0, "channels": defaultdict(int)})
    llm_used = llm_fallback = 0
    fallback_reasons = defaultdict(int)
    real_links = 0

    for a in db.query(Action).filter(Action.status == "SENT"):
        row = by_tier[a.tier]
        row["sent"] += 1
        row["spend_paise"] += a.cost_paise or 0
        row["channels"][a.channel] += 1
        if a.message_body:
            if a.llm_used:
                llm_used += 1
            else:
                llm_fallback += 1
                fallback_reasons[a.llm_rejected_reason or "UNKNOWN"] += 1
        if a.payment_link_is_real:
            real_links += 1

    return {
        "by_tier": [
            {"tier": t, **{k: (dict(v) if isinstance(v, defaultdict) else v)
                           for k, v in row.items()}}
            for t, row in sorted(by_tier.items())
        ],
        "messages_from_llm": llm_used,
        "messages_from_fallback": llm_fallback,
        "fallback_reasons": dict(fallback_reasons),
        "real_payment_links": real_links,
    }


def full_report(db: Session) -> Dict:
    # The detector is normally warmed by the orchestrator. When the report is
    # generated in a fresh process it has to warm itself, or the issuer-health
    # panel silently reports "all healthy" for a batch that held 97 retries.
    if not detector.health_report():
        from app.models import Payment
        detector.load_payments(
            [{c.name: getattr(p, c.name) for c in p.__table__.columns}
             for p in db.query(Payment)]
        )

    cases = _case_dicts(db)
    guardrails = guardrail_report(db)
    experiment = calculate_experiment_results(cases, guardrails)

    return {
        "run": {
            "batch_start": clock.iso(clock.BATCH_START),
            "batch_end": clock.iso(clock.BATCH_END),
            "ticks": clock.TICK_COUNT,
            "tick_hours": clock.TICK_HOURS,
            "cases": len(cases),
            "events": db.query(Event).count(),
        },
        "experiment": experiment,
        "per_class": per_class_breakdown(cases),
        "guardrails": guardrails,
        "delivery": delivery_report(db),
        "exceptions": exception_report(cases),
        "issuer_health": detector.health_report(at=clock.BATCH_START),
        "audit": verify_chain(db),
    }


# --------------------------------------------------------------------- markdown

def _rs(paise) -> str:
    return f"Rs {(paise or 0) / 100:,.2f}"


def _pct(x) -> str:
    return f"{(x or 0) * 100:.1f}%"


def render_run_environment(report: Dict) -> str:
    """
    The half of the numbers that depend on which services answered.

    These are deliberately kept out of EVALUATION.md. Message provenance and
    live link counts are a property of the machine that ran the batch, not of
    the seed — run it with an API key and 469 bodies come from the model, run
    it without one and 688 come from templates. Both are correct. Mixing them
    into the reproducible report made `make demo` produce a file that did not
    match the committed one, and CI was right to fail on it.
    """
    d = report["delivery"]
    lines = [
        "# Run environment",
        "",
        "Everything here depends on what was configured when the batch ran, so "
        "unlike `EVALUATION.md` it is **not** expected to reproduce. The "
        "recovery statistics do not depend on any of it: the outcome oracle is "
        "seeded, and a message that fell back to a template recovers exactly "
        "as often as one the model wrote.",
        "",
        "This file records the run that produced the committed database.",
        "",
        "## Where message bodies came from",
        "",
        "| Source | Count |",
        "| --- | --- |",
        f"| Written by the model | {d['messages_from_llm']} |",
        f"| Deterministic template | {d['messages_from_fallback']} |",
        "",
    ]

    if d["fallback_reasons"]:
        refused = {k: v for k, v in d["fallback_reasons"].items()
                   if not k.startswith("PROVIDER_ERROR")}
        unavailable = {k: v for k, v in d["fallback_reasons"].items()
                       if k.startswith("PROVIDER_ERROR")}

        if refused:
            lines += [
                "### Drafts the validator refused",
                "",
                "The guardrail doing its job against a live model, not a fixture.",
                "",
            ]
            for reason, n in sorted(refused.items(), key=lambda kv: -kv[1]):
                lines.append(f"- `{reason}` x{n}")
            lines.append("")

        if unavailable:
            lines += [
                "### Calls the provider did not answer",
                "",
                "A free tier rate-limits. The batch finished anyway, which is "
                "the entire point of having a deterministic fallback.",
                "",
            ]
            for reason, n in sorted(unavailable.items(), key=lambda kv: -kv[1]):
                lines.append(f"- `{reason}` x{n}")
            lines.append("")

    lines += [
        "## Payment links",
        "",
        f"Live Razorpay test-mode links minted: **{d['real_payment_links']}**. "
        "Every other link is simulated and flagged as such in the database, so "
        "nothing on the dashboard implies more live integration than there is.",
        "",
        "## Delivery by tier",
        "",
        "| Tier | Sent | Spend | Channels |",
        "| --- | --- | --- | --- |",
    ]
    for row in d["by_tier"]:
        channels = ", ".join(f"{k} x{v}" for k, v in sorted(row["channels"].items()))
        lines.append(
            f"| {row['tier']} | {row['sent']} | {_rs(row['spend_paise'])} | "
            f"{channels} |"
        )
    lines.append("")
    return "\n".join(lines)


def render_markdown(report: Dict) -> str:
    e = report["experiment"]
    g = report["guardrails"]
    run = report["run"]

    lines = [
        "# EVALUATION",
        "",
        "Every number on this page is produced by `make report` from the "
        "committed database. Re-run it and you get this file back — CI asserts "
        "exactly that on every push.",
        "",
        "Numbers that depend on which services were reachable — how many message "
        "bodies the model wrote, how many payment links were minted live — are "
        "in [docs/run-environment.md](docs/run-environment.md) instead, because "
        "they are a property of the machine that ran the batch rather than of "
        "the seed.",
        "",
        "## What is measured, and what is simulated",
        "",
        "**Real:** the classifier, the eleven-gate policy engine, the escalation "
        "ladder, the LLM validator, the hash-chained audit ledger, the "
        "treatment/control assignment, and every statistic below.",
        "",
        "**Simulated:** whether a customer actually paid. Outcomes come from a "
        "seeded oracle whose base rates are documented and justified in "
        "`docs/assumptions.md`. The agent has no access to it. No real customer "
        "was contacted and no real money moved.",
        "",
        "## Headline",
        "",
        "| Metric | Value |",
        "| --- | --- |",
        f"| Cases in the batch | {run['cases']} |",
        f"| Observation window | {run['ticks']} ticks x {run['tick_hours']}h "
        f"({run['ticks'] * run['tick_hours'] // 24} days) |",
        f"| Amount at risk | {_rs(e['amount_at_risk_paise'])} |",
        f"| Treatment arm | {e['treatment_n']} cases |",
        f"| Control arm (never contacted) | {e['control_n']} cases |",
        f"| Gross recovery, treatment | {_pct(e['treatment_rate'])} "
        f"({e['treatment_recovered']}/{e['treatment_n']}) |",
        f"| Gross recovery, control | {_pct(e['control_rate'])} "
        f"({e['control_recovered']}/{e['control_n']}) |",
        f"| **Net incremental lift** | **{e['net_lift'] * 100:+.1f} pp** "
        f"(95% CI {e['ci_lower'] * 100:.1f} to {e['ci_upper'] * 100:.1f}) |",
        f"| Value-weighted lift | {e['value_weighted_lift'] * 100:+.1f} pp of "
        f"amount at risk |",
        f"| **Incremental amount recovered** | **{_rs(e['value_incremental_paise'])}** |",
        f"| Intervention spend | {_rs(e['intervention_cost_paise'])} |",
        f"| ROI ({e['roi_basis']}) | {e['roi']:.0f}x |",
        f"| Lift needed to break even | "
        f"{e['breakeven_lift'] * 100:.3f} pp of amount at risk |",
    ]

    if e["cost_per_incremental_recovery_paise"]:
        lines.append(
            f"| Cost per incremental recovery | "
            f"{_rs(e['cost_per_incremental_recovery_paise'])} |"
        )

    lines += ["", "### Is the lift real?", ""]
    if e["is_significant"]:
        lines.append(
            f"Yes. The 95% confidence interval "
            f"({e['ci_lower'] * 100:.1f} to {e['ci_upper'] * 100:.1f} pp) excludes "
            f"zero, so at n={e['treatment_n']} treatment and n={e['control_n']} "
            f"control the effect is distinguishable from no effect."
        )
    else:
        lines.append(
            f"**No.** The 95% confidence interval "
            f"({e['ci_lower'] * 100:.1f} to {e['ci_upper'] * 100:.1f} pp) includes "
            f"zero, so this batch cannot distinguish the lift from noise. "
            f"Detecting an effect of this size at 80% power would need roughly "
            f"{e['required_n_per_arm']} cases per arm. The point estimate is "
            f"reported anyway rather than quietly dropped."
        )

    lines += [
        "",
        "## By recovery class",
        "",
        "Aggregate lift can hide a class that outreach is actively hurting.",
        "",
        "| Class | Treatment | Control | Lift | 95% CI | Spend |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in report["per_class"]:
        lines.append(
            f"| {row['recovery_class']} | {_pct(row['treatment_rate'])} "
            f"(n={row['treatment_n']}) | {_pct(row['control_rate'])} "
            f"(n={row['control_n']}) | {row['net_lift'] * 100:+.1f} pp | "
            f"{row['ci_lower'] * 100:.1f} to {row['ci_upper'] * 100:.1f} | "
            f"{_rs(row['spend_paise'])} |"
        )

    lines += [
        "",
        "## What the guardrails did",
        "",
        f"{g['total_blocks']} actions were refused, avoiding "
        f"{_rs(g['total_spend_avoided_paise'])} of spend and "
        f"{_rs(g['total_compliance_avoided_paise'])} of priced compliance "
        f"exposure.",
        "",
        "| Gate | Blocks | Cases | Spend avoided | Compliance avoided |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in g["gates"]:
        lines.append(
            f"| {row['gate']} {row['name']} | {row['blocks']} | "
            f"{row['cases_affected']} | {_rs(row['spend_avoided_paise'])} | "
            f"{_rs(row['compliance_avoided_paise'])} |"
        )

    zero_gates = [r for r in g["gates"] if r["blocks"] == 0]
    if zero_gates:
        names = ", ".join(f"{r['gate']} ({r['name']})" for r in zero_gates)
        lines += [
            "",
            f"{names} blocked nothing. That is the expected result, not a "
            "missing feature: the ladder never proposes the action those gates "
            "exist to refuse. They are the backstop that would catch a bug "
            "upstream, and if they ever fire there is one.",
        ]

    lines += [
        "",
        "## Honest exception list",
        "",
        "Everything the system did not recover, grouped by why. This is part of "
        "the result, not an appendix to it.",
        "",
        "| Reason | Cases | Amount left on the table |",
        "| --- | --- | --- |",
    ]
    for row in report["exceptions"]:
        lines.append(f"| {row['reason']} | {row['count']} | {_rs(row['amount_paise'])} |")

    audit = report["audit"]
    lines += [
        "",
        "## Audit integrity",
        "",
        f"- Ledger events: {audit['records']}",
        f"- Chain valid: **{audit['valid']}**",
        f"- Broken rows: {audit['broken_count']}",
        "",
        "Every decision above is reconstructable from the ledger. `make verify` "
        "recomputes the chain from genesis.",
        "",
        "## Limitations",
        "",
        "- Outcomes are simulated. The decision logic and the measurement are "
        "not, but no claim is made about real-world recovery rates.",
        "- One batch, one seed. The base rates in `docs/assumptions.md` are "
        "stated estimates, not measurements from production traffic.",
        "- The control arm is untouched by this system only. In production it "
        "would still receive the payment provider's own default retries.",
        "- Voice is scripted and validated end-to-end, but rendered as audio "
        "rather than dialled; there is no live telephony integration.",
        "- **The ROI figure counts variable messaging cost only.** It excludes "
        "platform, engineering, and support load. Treat it as an upper bound on "
        "the unit economics, not as a business case. The break-even line above "
        "is the more useful number: it is how small the lift could have been "
        "before the campaign stopped paying for its own messages.",
        "- Two lift figures are reported. The case-count lift weights a small "
        "cart the same as a large invoice; the value-weighted lift does not. "
        "They differ, and both are shown rather than whichever is larger.",
        "",
    ]
    return "\n".join(lines)
