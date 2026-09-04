"use client";

import { useEffect, useState } from "react";

import { fetchQueue, postQueueAction, type QueueResponse } from "@/lib/api";
import { pp, rupees, rupeesShort } from "@/lib/format";
import {
  Callout, Card, CaseLink, Failed, Loading, Page, Pill, Stat,
} from "@/components/ui";
import {
  AlertIcon, CasesIcon, RupeeIcon, ShieldIcon, TerminalIcon,
} from "@/components/icons";

/**
 * The human-review queue.
 *
 * Tier 4 is 89% of total spend and had nowhere to go: cases were routed to a
 * person, billed for their attention, and then left with no way to work them
 * or close one. This is that missing half.
 *
 * The economics sit above the list rather than below it, because thirty-odd
 * rows is a short queue and whether working it is worth anything is the only
 * interesting question about it. The finding is a correction of an earlier,
 * overstated one: this lane is not "not paying for itself" — in expectation
 * it looks worth it, and it cannot be measured at this sample size, which is
 * a different and more defensible claim.
 */
export default function Queue() {
  const [data, setData] = useState<QueueResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [operator, setOperator] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  function load() {
    fetchQueue().then(setData).catch((e: Error) => setError(e.message));
  }

  useEffect(load, []);

  async function submit(caseId: string, action: string) {
    if (!operator.trim() || !reason.trim()) {
      setActionError("Both operator and reason are required.");
      return;
    }
    setBusy(true);
    setActionError(null);
    try {
      await postQueueAction(caseId, action, operator.trim(), reason.trim());
      setOpen(null);
      setReason("");
      load();
    } catch (e) {
      // The API's 422 carries the reason — a missing field, an already-closed
      // case, or the control-arm guard. Surface it rather than a generic
      // failure; that message is the point of the endpoint.
      setActionError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (error) return <Failed error={error} />;
  if (!data) return <Loading what="the queue" />;

  const e = data.economics;

  return (
    <Page
      crumbs={[{ label: "RecoverOS" }, { label: "Review Queue", accent: true }]}
      title="The human-review queue"
      subtitle={`Risk-blocked cases the agent will never auto-contact. Routed to a person, billed at ${rupees(e.cost_per_review_paise)} of their time, and — until this page — left with nowhere to go.`}
    >
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-6">
        <Stat
          label="Share of total spend"
          value={`${(e.share_of_total_spend * 100).toFixed(0)}%`}
          tone="warn"
          icon={<RupeeIcon size={17} />}
          sub={`${rupees(e.spend_paise)} of agent time`}
        />
        <Stat
          label="Measured lift"
          value={pp(e.measured_lift)}
          tone={e.is_significant ? "good" : "muted"}
          icon={<ShieldIcon size={17} />}
          sub={`95% CI ${pp(e.ci_lower)} to ${pp(e.ci_upper)} — ${
            e.is_significant ? "significant" : "not significant"
          }`}
        />
        <Stat
          label="Cases needed to tell"
          value={e.required_n_per_arm ? e.required_n_per_arm.toLocaleString("en-IN") : "—"}
          icon={<CasesIcon size={17} />}
          sub={`per arm — have ${e.cases} and ${e.control_cases}`}
        />
      </div>

      <Card title="Is this lane worth it?" icon={<AlertIcon size={18} />}>
        <p className="text-[14px] text-[var(--ink-2)] leading-relaxed mb-3">
          Expected incremental recovery on our assumptions is{" "}
          <span className="text-[var(--ink)] tnum">
            {rupees(e.expected_incremental_paise)}
          </span>{" "}
          against{" "}
          <span className="text-[var(--ink)] tnum">{rupees(e.spend_paise)}</span>{" "}
          spent — in expectation, worth it. But detecting a{" "}
          {(e.assumed_marginal_lift * 100).toFixed(0)}% lift needs roughly{" "}
          <span className="text-[var(--ink)] tnum">
            {e.required_n_per_arm?.toLocaleString("en-IN")}
          </span>{" "}
          cases per arm, and this batch has {e.cases} and {e.control_cases}.
        </p>
        <Callout tone="warn">{e.reading}</Callout>
        {e.below_break_even > 0 && (
          <p className="text-[13px] text-[var(--ink-3)] mt-3">
            Separately, and independent of sample size:{" "}
            <span className="text-[var(--ink)]">{e.below_break_even} cases</span>{" "}
            below the {rupees(e.break_even_paise ?? 0)} break-even can never
            pay back a call, however large the sample gets.
          </p>
        )}
      </Card>

      <div className="mt-6">
        <Card
          title="Queue"
          hint={`${data.queue.length} cases · control arm excluded`}
          icon={<CasesIcon size={18} />}
        >
          {data.queue.length === 0 ? (
            <p className="text-[13.5px] text-[var(--ink-3)]">
              Nothing waiting on a person right now.
            </p>
          ) : (
            <div className="space-y-2">
              {data.queue.map((row) => (
                <div
                  key={row.case_id}
                  className="border-b border-[var(--line)] last:border-0 pb-3"
                >
                  <div className="flex items-center justify-between gap-3">
                    <div className="flex items-center gap-2">
                      <CaseLink id={row.case_id} />
                      <span className="text-[12px] text-[var(--ink-3)]">
                        {row.state}
                      </span>
                      {row.below_break_even && (
                        <Pill className="text-[var(--warn)] border-[var(--warn)]/30">
                          below break-even
                        </Pill>
                      )}
                    </div>
                    <div className="flex items-center gap-3">
                      <span className="tnum text-[13.5px] text-[var(--ink)]">
                        {rupeesShort(row.amount_at_risk_paise)}
                      </span>
                      <button
                        onClick={() =>
                          setOpen(open === row.case_id ? null : row.case_id)
                        }
                        className="text-[12px] px-2.5 py-1 rounded border border-[var(--line-strong)] text-[var(--ink-2)] hover:text-[var(--ink)] hover:border-[var(--ink-3)] transition"
                      >
                        {open === row.case_id ? "Cancel" : "Act"}
                      </button>
                    </div>
                  </div>

                  {open === row.case_id && (
                    <div className="mt-3 pl-1 space-y-2">
                      <div className="flex gap-2">
                        <input
                          value={operator}
                          onChange={(e) => setOperator(e.target.value)}
                          placeholder="your name"
                          className="flex-1 text-[13px] bg-[var(--surface-inset)] border border-[var(--line)] rounded px-2.5 py-1.5 text-[var(--ink)] placeholder:text-[var(--ink-4)]"
                        />
                      </div>
                      <textarea
                        value={reason}
                        onChange={(e) => setReason(e.target.value)}
                        placeholder="reason — required, and kept in the audit trail"
                        rows={2}
                        className="w-full text-[13px] bg-[var(--surface-inset)] border border-[var(--line)] rounded px-2.5 py-1.5 text-[var(--ink)] placeholder:text-[var(--ink-4)]"
                      />
                      {actionError && (
                        <p className="text-[12px] text-[var(--critical)]">
                          {actionError}
                        </p>
                      )}
                      <div className="flex flex-wrap gap-2">
                        {data.actions.map((a) => (
                          <button
                            key={a.action}
                            disabled={busy}
                            onClick={() => submit(row.case_id, a.action)}
                            title={a.describes}
                            className="text-[12px] px-2.5 py-1.5 rounded border border-[var(--line-strong)] text-[var(--ink-2)] hover:text-[var(--ink)] hover:border-[var(--treatment)]/50 transition disabled:opacity-50"
                          >
                            {a.action.replaceAll("_", " ").toLowerCase()}
                          </button>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>

      <div className="mt-4">
        <Card title="What each action does" icon={<TerminalIcon size={18} />}>
          <div className="space-y-2">
            {data.actions.map((a) => (
              <div key={a.action} className="text-[13px]">
                <span className="font-mono text-[var(--ink)]">
                  {a.action}
                </span>
                <span className="text-[var(--ink-3)]"> — {a.describes}</span>
              </div>
            ))}
          </div>
          <Callout>
            Every action lands in the same hash-chained ledger as the agent&apos;s
            own decisions, with the operator named and the reason kept. A
            control-arm case cannot be acted on — the call is refused, not
            hidden, because a queue that merely omits them still lets one
            through by direct id.
          </Callout>
        </Card>
      </div>
    </Page>
  );
}
