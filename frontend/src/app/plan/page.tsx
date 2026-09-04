"use client";

import { useRef, useState } from "react";

import { API_BASE, type IngestResult } from "@/lib/api";
import { rupees, rupeesShort } from "@/lib/format";
import { Callout, Card, Page, Pill, Stat } from "@/components/ui";
import {
  AlertIcon, CasesIcon, RupeeIcon, ShieldAlertIcon, TerminalIcon,
} from "@/components/icons";

/**
 * Point the policy at a real backlog.
 *
 * The fair objection to a simulation is that it might only work on its own
 * tidy data. This is the answer a merchant can check for themselves: their
 * export, their column names, and what the eleven gates would actually do
 * with it.
 *
 * Nothing is stored. The file is posted, planned against in memory, and
 * dropped — the response carries counts and money, never a row — and the page
 * says so, because "we deleted it" is worth nothing unless it is stated.
 */
export default function Plan() {
  const [result, setResult] = useState<IngestResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  async function send(file: File) {
    setBusy(true);
    setError(null);
    try {
      const form = new FormData();
      form.append("file", file);
      const res = await fetch(`${API_BASE}/ingest/plan`, {
        method: "POST",
        body: form,
      });
      const body = await res.json();
      if (!res.ok) {
        // The API's 422 carries the actionable message — which column was
        // missing and which headers were found. Showing "422" instead would
        // waste the work that went into writing it.
        throw new Error(body.detail ?? `${res.status} ${res.statusText}`);
      }
      setResult(body as IngestResult);
    } catch (e) {
      setError((e as Error).message);
      setResult(null);
    } finally {
      setBusy(false);
    }
  }

  const p = result?.plan;

  return (
    <Page
      crumbs={[{ label: "RecoverOS" }, { label: "Plan a backlog", accent: true }]}
      title="What would this do to your data?"
      subtitle="Drop in a CSV of failed payments. The same classifier, ladder and eleven gates the batch uses will report how each row is routed, what would be sent, and what would be refused — with your column names, not ours."
    >
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          const file = e.dataTransfer.files?.[0];
          if (file) void send(file);
        }}
        className={`rounded-lg border border-dashed p-8 text-center transition-colors ${
          dragging
            ? "border-[var(--treatment)] bg-[var(--surface-raised)]"
            : "border-[var(--line-strong)] bg-[var(--surface)]"
        }`}
      >
        <input
          ref={inputRef}
          type="file"
          accept=".csv,text/csv"
          hidden
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) void send(file);
          }}
        />
        <p className="text-[15px] text-[var(--ink)] mb-1">
          {busy ? "Planning…" : "Drop a CSV here"}
        </p>
        <p className="text-[13px] text-[var(--ink-3)] mb-4">
          Or{" "}
          <button
            type="button"
            onClick={() => inputRef.current?.click()}
            className="text-[var(--treatment)] underline underline-offset-2"
          >
            choose a file
          </button>
          . Needs an id column and an amount column; everything else improves
          the answer.
        </p>
        <p className="text-[12px] text-[var(--ink-4)] font-mono">
          nothing is uploaded to storage · parsed in memory · dropped
        </p>
      </div>

      {error && (
        <div className="mt-4">
          <Callout tone="bad">{error}</Callout>
        </div>
      )}

      {result && p && (
        <>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mt-6">
            <Stat
              label="Rows read"
              value={result.rows_usable.toLocaleString("en-IN")}
              icon={<CasesIcon size={17} />}
              sub={
                result.rows_rejected
                  ? `${result.rows_rejected} rejected, listed below`
                  : "every row usable"
              }
            />
            <Stat
              label="Would contact"
              value={`${p.would_contact.toLocaleString("en-IN")} of ${p.cases.toLocaleString("en-IN")}`}
              icon={<TerminalIcon size={17} />}
              sub={`${p.no_action_possible.toLocaleString("en-IN")} have no useful action at all`}
            />
            <Stat
              label="Day-one spend"
              value={rupees(p.planned_spend_paise)}
              icon={<RupeeIcon size={17} />}
              sub={`against ${rupeesShort(p.amount_at_risk_paise)} at risk`}
            />
          </div>

          <div className="mt-4">
            <Card
              title="Projected incremental recovery"
              icon={<RupeeIcon size={18} />}
              hint="A range, on purpose"
            >
              <p className="text-[26px] text-[var(--ink)] tnum mb-1">
                {rupeesShort(p.projection.low_paise)} –{" "}
                {rupeesShort(p.projection.high_paise)}
              </p>
              <p className="text-[13px] text-[var(--ink-3)] mb-4">
                At our assumptions:{" "}
                {rupees(p.projection.at_our_assumptions_paise)}
              </p>
              <Callout tone="warn">{p.projection.basis}</Callout>
            </Card>
          </div>

          <div className="grid lg:grid-cols-2 gap-4 mt-4">
            <Card title="How your rows were routed" icon={<CasesIcon size={18} />}>
              <div className="space-y-2">
                {p.by_class.map((row) => (
                  <div
                    key={row.recovery_class}
                    className="flex items-baseline justify-between text-[13.5px]"
                  >
                    <span className="font-mono text-[var(--ink-2)]">
                      {row.recovery_class}
                    </span>
                    <span className="tnum text-[var(--ink)]">{row.cases}</span>
                  </div>
                ))}
              </div>
            </Card>

            <Card
              title="What the gates would refuse"
              icon={<ShieldAlertIcon size={18} />}
            >
              {p.refusals.length === 0 ? (
                <p className="text-[13.5px] text-[var(--ink-3)]">
                  Nothing structurally refused in this backlog.
                </p>
              ) : (
                <div className="space-y-3">
                  {p.refusals.map((row) => (
                    <div key={row.gate}>
                      <div className="flex items-baseline justify-between text-[13.5px] mb-1">
                        <span className="font-mono text-[var(--ink)]">
                          {row.gate}
                        </span>
                        <span className="tnum text-[var(--ink)]">
                          {row.blocks}
                        </span>
                      </div>
                      <div className="flex flex-wrap gap-1.5">
                        {Object.entries(row.reasons).map(([reason, n]) => (
                          <Pill key={reason}>
                            {reason} ×{n}
                          </Pill>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </Card>
          </div>

          <div className="mt-4">
            <Card
              title="What was matched to what"
              hint={`amount read as ${result.amount_unit}`}
              icon={<TerminalIcon size={18} />}
            >
              <div className="grid sm:grid-cols-2 gap-x-8 gap-y-1.5">
                {Object.entries(result.mapping).map(([field, header]) => (
                  <div
                    key={field}
                    className="flex items-baseline justify-between gap-3 text-[12.5px] font-mono"
                  >
                    <span className="text-[var(--ink-3)]">{field}</span>
                    <span className="text-[var(--ink)] truncate">{header}</span>
                  </div>
                ))}
              </div>
              {result.unmapped_headers.length > 0 && (
                <p className="text-[12px] text-[var(--ink-4)] mt-3 font-mono">
                  ignored: {result.unmapped_headers.join(", ")}
                </p>
              )}
            </Card>
          </div>

          {result.problems.length > 0 && (
            <div className="mt-4">
              <Card
                title="Rows that could not be used"
                hint="With line numbers, so they can be found"
                icon={<AlertIcon size={18} />}
              >
                <div className="space-y-1.5">
                  {result.problems.map((problem) => (
                    <div
                      key={`${problem.line}-${problem.problem}`}
                      className="text-[12.5px] font-mono text-[var(--ink-3)]"
                    >
                      <span className="text-[var(--ink-2)]">
                        line {problem.line}
                      </span>
                      {" — "}
                      {problem.problem}
                    </div>
                  ))}
                </div>
                {result.rows_rejected > result.problems.length && (
                  <p className="text-[12px] text-[var(--ink-4)] mt-3">
                    and {result.rows_rejected - result.problems.length} more
                  </p>
                )}
              </Card>
            </div>
          )}

          <div className="mt-4">
            <Card title="What this plan assumed">
              <ul className="space-y-2 m-0 p-0 list-none">
                {p.assumptions.map((line) => (
                  <li
                    key={line}
                    className="text-[13.5px] text-[var(--ink-2)] leading-relaxed pl-4 relative"
                  >
                    <span className="absolute left-0 text-[var(--ink-4)]">–</span>
                    {line}
                  </li>
                ))}
              </ul>
            </Card>
          </div>
        </>
      )}
    </Page>
  );
}
