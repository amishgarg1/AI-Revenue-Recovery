"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import {
  fetchDelivery, fetchGuardrails, fetchPolicy,
  type DeliveryReport, type GuardrailReport, type PolicyBook, type PolicyConfig,
} from "@/lib/api";
import { CHANNEL_LABELS, rupees, rupeesShort } from "@/lib/format";
import {
  Bar, Callout, Card, Failed, Loading, Page, Pill, Stat,
} from "@/components/ui";
import {
  ChartUpIcon, RupeeIcon, ShieldAlertIcon, ShieldIcon, TerminalIcon,
} from "@/components/icons";

const hour = (h: number) => `${h % 12 || 12}${h < 12 ? "AM" : "PM"}`;

/**
 * What each gate is for, in the numbers actually in force.
 *
 * These used to be a fixed table quoting 9PM–9AM and 15%. Those are now a
 * merchant's settings, so a hardcoded description would confidently explain
 * somebody else's policy the moment one was configured.
 */
function gatePurpose(p: PolicyConfig): Record<string, string> {
  return {
    G01: "Never contact someone who revoked consent or sits on the DND registry",
    G02: `No commercial contact ${hour(p.quiet_start_ist)}–${hour(p.quiet_end_ist)} IST; voice only ${hour(p.voice_start_ist)}–${hour(p.voice_end_ist)}`,
    G03: `${p.max_touches_24h} touch per customer per day, ${p.max_touches_7d} per week — across all their cases`,
    G04: `${p.max_touches_per_case} recovery attempts per case, then stop`,
    G05: `${p.cooldown_hours} hours between two touches on the same case`,
    G06: `Never spend more than ${Math.round(p.max_cost_ratio * 100)}% of the amount at risk, and never chase below ₹${p.min_viable_amount_paise / 100}`,
    G07: "Risk-blocked cases go to a human and are never auto-contacted",
    G08: "Hold retries while the issuer is down instead of burning attempts",
    G09: "Stop the moment the order is settled through another route",
    G10: "Closed is closed, and a promise to pay is honoured until its date",
    G11: "No skipping tiers — voice has to be earned",
  };
}

export default function Guardrails() {
  const [data, setData] = useState<
    { g: GuardrailReport; d: DeliveryReport; p: PolicyBook } | null
  >(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([fetchGuardrails(), fetchDelivery(), fetchPolicy()])
      .then(([g, d, p]) => setData({ g, d, p }))
      .catch((e: Error) => setError(e.message));
  }, []);

  if (error) return <Failed error={error} />;
  if (!data) return <Loading what="guardrails" />;

  const { g, d, p } = data;
  const purpose = gatePurpose(p.defaults);
  const merchants = Object.entries(p.merchants);
  // A provider outage and a refused draft both end in a fallback, but only one
  // of them is the guardrail doing its job. Counting them together would
  // overstate what the validator caught.
  const rejectedByValidator = Object.entries(d.fallback_reasons)
    .filter(([reason]) => !reason.startsWith("PROVIDER_ERROR"))
    .reduce((n, [, count]) => n + count, 0);
  const maxBlocks = Math.max(...g.gates.map((x) => x.blocks), 1);
  const silent = g.gates.filter((x) => x.blocks === 0);

  return (
    <Page
      crumbs={[{ label: "RecoverOS" }, { label: "Guardrails", accent: true }]}
      title="Guardrails"
      subtitle="Eleven gates, evaluated in order on every proposed action. What they refused, and what that was worth."
    >
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-6">
        <Stat
          label="Actions refused"
          value={g.total_blocks.toLocaleString("en-IN")}
          tone="warn"
          icon={<ShieldAlertIcon size={17} />}
          sub={`Fired by ${g.gates.filter((x) => x.blocks > 0).length} of the ${g.gates.length} gates`}
        />
        <Stat
          label="Spend avoided"
          value={rupees(g.total_spend_avoided_paise)}
          icon={<RupeeIcon size={17} />}
          sub="Messages that would have gone out and been wasted"
        />
        <Stat
          label="Compliance exposure avoided"
          value={rupeesShort(g.total_compliance_avoided_paise)}
          tone="good"
          icon={<ShieldIcon size={17} />}
          sub={`Priced at ₹${p.defaults.compliance_risk_paise / 100} per avoided consent, DND, quiet-hours or frequency violation`}
        />
      </div>

      <Card
        title="Whose rules these are"
        hint={p.source ? "config/policy.yaml" : "built-in defaults, no config file"}
        icon={<ShieldIcon size={18} />}
      >
        <p className="text-[14px] text-[var(--ink-2)] leading-relaxed">
          The gates below enforce these numbers; they do not own them. Quiet
          hours are{" "}
          <span className="text-[var(--ink)]">
            {hour(p.defaults.quiet_start_ist)}–{hour(p.defaults.quiet_end_ist)}
          </span>{" "}
          because that is the Indian norm, and a merchant elsewhere disagrees
          before they finish reading it. So they live in configuration and
          resolve per merchant.
        </p>

        {merchants.length > 0 && (
          <div className="mt-4 space-y-2">
            {merchants.map(([id, m]) => (
              <div
                key={id}
                className="flex flex-wrap items-baseline gap-x-3 gap-y-1 text-[12.5px] border-t border-[var(--line)] pt-2"
              >
                <span className="font-mono text-[var(--ink)]">{id}</span>
                <span className="text-[var(--ink-3)]">
                  quiet {hour(m.quiet_start_ist)}–{hour(m.quiet_end_ist)}
                </span>
                <span className="text-[var(--ink-3)]">
                  {m.max_touches_7d}/week
                </span>
                <span className="text-[var(--ink-3)]">
                  floor ₹{m.min_viable_amount_paise / 100}
                </span>
                <span className="text-[var(--ink-3)]">
                  cap {Math.round(m.max_cost_ratio * 100)}%
                </span>
              </div>
            ))}
          </div>
        )}

        <Callout>
          Same engine, different answers. A ₹250 order clears the default floor
          and is refused for a merchant whose support costs more — and the gate
          explains itself in that merchant&apos;s terms rather than quoting a
          constant from the source.
        </Callout>
      </Card>

      <div className="mt-6" />

      <Card
        title="Every gate, including the quiet ones"
        hint="Evaluated in order on every proposed action"
        icon={<ShieldIcon size={18} />}
      >
        <div className="space-y-4">
          {g.gates.map((gate) => (
            <div key={gate.gate} className="border-b border-[var(--line)] pb-4 last:border-0">
              <div className="flex items-baseline justify-between gap-4 mb-1.5">
                <div className="flex items-baseline gap-2">
                  <span className="font-mono text-sm text-[var(--ink)]">{gate.gate}</span>
                  <span className="text-sm text-[var(--ink)]">{gate.name}</span>
                </div>
                <div className="text-right shrink-0">
                  <span className="font-mono text-sm text-[var(--ink)]">
                    {gate.blocks}
                  </span>
                  <span className="text-xs text-[var(--ink-4)] ml-2">
                    {gate.cases_affected} cases
                  </span>
                </div>
              </div>
              <p className="text-xs text-[var(--ink-3)] mb-2">{purpose[gate.gate]}</p>
              <Bar value={gate.blocks} max={maxBlocks} tone={gate.blocks ? "guard" : "muted"} />
              {Object.keys(gate.reasons).length > 0 && (
                <div className="flex flex-wrap gap-1.5 mt-2">
                  {Object.entries(gate.reasons)
                    .sort((a, b) => b[1] - a[1])
                    .map(([reason, n]) => (
                      <Link key={reason} href={`/cases?blocked_by=${gate.gate}`}>
                        <Pill>
                          {reason} ×{n}
                        </Pill>
                      </Link>
                    ))}
                </div>
              )}
            </div>
          ))}
        </div>

        {silent.length > 0 && (
          <Callout>
            {silent.map((s) => `${s.gate} (${s.name})`).join(", ")} refused
            nothing. That is the expected result, not a missing feature: the
            ladder never proposes the action those gates exist to prevent. They
            are the backstop that would catch a bug upstream — if one ever
            fires, there is one.
          </Callout>
        )}
      </Card>

      <div className="grid lg:grid-cols-2 gap-6 mt-6">
        <Card
          title="What went out"
          hint="Cheapest tier first, no skipping"
          icon={<ChartUpIcon size={18} />}
        >
          <div className="space-y-3">
            {d.by_tier.map((tier) => (
              <div key={tier.tier} className="flex items-center gap-4 text-sm">
                <span className="font-mono text-[var(--ink-3)] w-14 shrink-0">
                  Tier {tier.tier}
                </span>
                <span className="text-[var(--ink-2)] flex-1">
                  {Object.entries(tier.channels)
                    .map(([ch, n]) => `${CHANNEL_LABELS[ch] ?? ch} ×${n}`)
                    .join(", ")}
                </span>
                <span className="font-mono text-[var(--ink)] w-16 text-right">
                  {tier.sent}
                </span>
                <span className="font-mono text-[var(--ink-3)] w-20 text-right">
                  {rupees(tier.spend_paise)}
                </span>
              </div>
            ))}
          </div>
        </Card>

        <Card
          title="Where message bodies came from"
          hint="The model drafts; the code decides and fills in every number"
          icon={<TerminalIcon size={18} />}
          tone="muted"
        >
          <div className="grid grid-cols-2 gap-4 mb-4">
            <Stat label="From the LLM" value={String(d.messages_from_llm)} />
            <Stat
              label="From fallback templates"
              value={String(d.messages_from_fallback)}
            />
          </div>
          {Object.keys(d.fallback_reasons).length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {Object.entries(d.fallback_reasons)
                .sort((a, b) => b[1] - a[1])
                .map(([reason, n]) => (
                  <Pill key={reason}>
                    {reason} ×{n}
                  </Pill>
                ))}
            </div>
          )}
          <Callout>
            {d.messages_from_llm === 0 ? (
              "No LLM provider is configured in this deployment, so every body came from a deterministic template. That is the honest state rather than a hidden one — and it is exactly what happens when the provider is down mid-batch."
            ) : (
              <>
                Templates are cached per (class, tier, language, channel) and
                each combination is asked once, so{" "}
                <span className="text-[var(--ink)] font-mono">
                  {d.messages_from_llm + d.messages_from_fallback}
                </span>{" "}
                messages cost a few dozen provider calls rather than one each.
                Of the {d.messages_from_fallback} that fell back,{" "}
                <span className="text-[var(--ink)] font-mono">
                  {rejectedByValidator}
                </span>{" "}
                were the model&apos;s own drafts being refused — a missing
                amount token, a voice script with no opt-out, an SMS one
                character over the limit. The rest were the provider being
                unavailable, which the batch survived either way.
              </>
            )}
          </Callout>
          <Callout>
            {d.real_payment_links} live Razorpay test-mode links were minted;
            the rest are simulated and flagged as such in the database, so no
            chart implies more live integration than there is.
          </Callout>
        </Card>
      </div>
    </Page>
  );
}
