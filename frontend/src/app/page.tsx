"use client";

import { useEffect, useState } from "react";

import ActivityRibbon from "@/components/charts/ActivityRibbon";
import DivergenceChart from "@/components/charts/DivergenceChart";
import GrossSplit from "@/components/charts/GrossSplit";
import MoneyFlow from "@/components/charts/MoneyFlow";
import {
  BanIcon,
  BarStackIcon,
  ChartUpIcon,
  LedgerIcon,
  RupeeIcon,
  ShieldAlertIcon,
  ShieldIcon,
  TrendingUpIcon,
} from "@/components/icons";
import {
  Callout,
  Card,
  Failed,
  HeroStat,
  LinkPill,
  Loading,
  Page,
  Pill,
  Stat,
} from "@/components/ui";
import {
  fetchExperiment,
  fetchFlow,
  fetchGuardrails,
  fetchIssuerHealth,
  fetchTimeline,
  verifyLedger,
  type AuditStatus,
  type ClassRow,
  type ExperimentResult,
  type Flow,
  type GuardrailReport,
  type IssuerHealth,
  type Timeline,
} from "@/lib/api";
import { pct, pp, rupees, rupeesShort } from "@/lib/format";

interface Data {
  experiment: ExperimentResult;
  perClass: ClassRow[];
  timeline: Timeline;
  flow: Flow;
  guardrails: GuardrailReport;
  issuers: IssuerHealth[];
  audit: AuditStatus;
}

export default function CommandCenter() {
  const [data, setData] = useState<Data | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([
      fetchExperiment(),
      fetchTimeline(),
      fetchFlow(),
      fetchGuardrails(),
      fetchIssuerHealth(),
      verifyLedger(),
    ])
      .then(([exp, timeline, flow, guardrails, issuers, audit]) =>
        setData({
          experiment: exp.overall,
          perClass: exp.per_class,
          timeline,
          flow,
          guardrails,
          issuers: issuers.issuers,
          audit,
        }),
      )
      .catch((e: Error) => setError(e.message));
  }, []);

  if (error) return <Failed error={error} />;
  if (!data) return <Loading what="command center" />;

  const { experiment: e, perClass, timeline, flow, guardrails, issuers, audit } = data;
  const degraded = issuers.filter((i) => i.degraded);
  const insignificant = perClass.filter((c) => !c.is_significant);

  return (
    <Page
      rail
      title="Revenue at risk, and what came back"
      subtitle="Failed payments, abandoned carts and overdue invoices — worked for seven simulated days behind eleven policy gates, and measured against a fifth of the batch the agent was never allowed to touch."
    >
      {/* ── The hero. Two numbers, and the honest one is bigger. ───────── */}
      <div className="grid lg:grid-cols-[1.15fr_1fr] gap-5 mb-5 hero-wash stagger">
        <HeroStat
          label="Incremental revenue recovered"
          value={rupeesShort(e.value_incremental_paise)}
          aside={`of ${rupeesShort(e.amount_at_risk_paise)} at risk`}
          tone="good"
          icon={<TrendingUpIcon size={17} />}
          figure={
            <GrossSplit
              gross={e.treatment_gross_recovered_paise}
              incremental={e.value_incremental_paise}
            />
          }
        >
          Gross recovery was{" "}
          <span className="text-[var(--recovered)] font-mono">
            {rupeesShort(e.treatment_gross_recovered_paise)}
          </span>
          . But{" "}
          <span className="text-[var(--treatment)] font-mono">
            {pct(e.control_rate)}
          </span>{" "}
          of untouched cases came back on their own, and that share is not ours
          to claim. Only the difference is.
        </HeroStat>

        <div className="grid grid-cols-2 gap-5">
          <Stat
            label="Net incremental lift"
            value={pp(e.net_lift)}
            tone={e.is_significant ? "good" : "warn"}
            icon={<ChartUpIcon size={17} />}
            sub={
              <>
                95% CI {(e.ci_lower * 100).toFixed(1)} to{" "}
                {(e.ci_upper * 100).toFixed(1)}
                <br />
                {e.is_significant ? "excludes zero" : "includes zero"}
              </>
            }
          />
          <Stat
            label="Spend"
            value={rupees(e.intervention_cost_paise)}
            icon={<RupeeIcon size={17} />}
            sub={`${e.roi.toFixed(0)}× on ${e.roi_basis}`}
          />
          <Stat
            label="Actions refused"
            value={guardrails.total_blocks.toLocaleString("en-IN")}
            tone="warn"
            icon={<ShieldAlertIcon size={17} />}
            sub={`by ${guardrails.gates.filter((g) => g.blocks > 0).length} of ${guardrails.gates.length} gates`}
          />
          <Stat
            label="Audit ledger"
            value={audit.valid ? "VALID" : "BROKEN"}
            tone={audit.valid ? "accent" : "bad"}
            icon={<LedgerIcon size={17} />}
            sub={`${audit.records.toLocaleString("en-IN")} hash-chained events`}
          />
        </div>
      </div>

      {/* ── The counterfactual, drawn ──────────────────────────────────── */}
      <Card
        title="Treatment vs control, over seven days"
        hint="The wedge between the two lines is the lift. Everything else on this page is downstream of it."
        icon={<TrendingUpIcon size={18} />}
        aside={<LinkPill href="/experiment">methodology</LinkPill>}
        className="mb-4"
      >
        <DivergenceChart
          rows={timeline.rows}
          outages={timeline.outages}
          armTotals={timeline.arm_totals}
        />
        <Callout>
          The control arm is assigned by hashing the order id, so it was fixed
          before anything was known about any case and anyone can recompute it.
          Control cases are classified and measured but never contacted and never
          billed — there is a test that fails if a single action lands on one.
        </Callout>
      </Card>

      {/* ── The rhythm of the work ─────────────────────────────────────── */}
      <Card
        title="What the agent did, tick by tick"
        hint="Two-hour ticks. Sent above the line, refused below."
        icon={<BarStackIcon size={18} />}
        className="mb-4"
      >
        <ActivityRibbon rows={timeline.rows} />
        <Callout>
          Activity collapses to nothing every night — that is the quiet-hours
          gate, not a gap in the data. The refusal band is thickest on day one,
          when the issuer is still degraded and the per-customer frequency caps
          are saturated from the previous system&apos;s outreach.
        </Callout>
      </Card>

      <div className="grid lg:grid-cols-[1.3fr_1fr] gap-5 stagger">
        <Card
          title="Where the money went"
          hint="The filled part is the share of that lane's money that came back"
          icon={<RupeeIcon size={18} />}
          tone="good"
        >
          <MoneyFlow classes={flow.by_class} />
        </Card>

        <div className="space-y-4">
          <Card
            title="Issuer health"
            hint="z-scored against each issuer's own baseline"
            icon={<ShieldIcon size={18} />}
          >
            <div className="space-y-1.5">
              {issuers.map((i) => (
                <div
                  key={i.issuer}
                  className="flex items-center justify-between px-3 py-2.5 bg-[var(--surface-inset)]/70 rounded-lg border border-[var(--line)]"
                >
                  <span className="text-[13px] font-mono text-[var(--ink-2)]">
                    {i.issuer}
                  </span>
                  {i.degraded ? (
                    <Pill className="text-[var(--warn)] border-[var(--warn)]/30 bg-[var(--warn)]/10">
                      degraded · peak {i.peak_failures_in_window}
                    </Pill>
                  ) : (
                    <Pill className="text-[var(--recovered)] border-[var(--recovered)]/30 bg-[var(--recovered)]/10">
                      healthy
                    </Pill>
                  )}
                </div>
              ))}
            </div>
            {degraded.length > 0 && (
              <Callout>
                {degraded.map((d) => d.issuer).join(", ")} was failing far above
                its own baseline when the batch began. Retries against it were
                held rather than spent, and released once it recovered — visible
                as the amber band on the chart above.
              </Callout>
            )}
          </Card>

          {/* The finding that works against us, on the landing page. */}
          <Card
            title="What this batch cannot claim"
            icon={<BanIcon size={18} />}
            tone="warn"
          >
            <div className="space-y-2.5">
              {insignificant.map((c) => (
                <div
                  key={c.recovery_class}
                  className="flex items-center gap-3 text-[13px]"
                >
                  <span className="font-mono text-[12px] text-[var(--ink-2)] w-40 shrink-0">
                    {c.recovery_class}
                  </span>
                  <span className="font-mono text-[12px] text-[var(--recovered)] tnum">
                    {pp(c.net_lift)}
                  </span>
                  <span className="ml-auto text-[10px] font-mono uppercase tracking-wide text-[var(--ink-4)]">
                    CI includes 0
                  </span>
                </div>
              ))}
            </div>
            <Callout tone="warn">
              {insignificant.length} of {perClass.length} recovery classes cannot
              be distinguished from doing nothing at this sample size. The
              aggregate lift is significant; these lanes individually are not,
              and saying so here is cheaper than being asked.
            </Callout>
          </Card>
        </div>
      </div>
    </Page>
  );
}
