"use client";

import { useEffect, useState } from "react";

import { fetchCases, fetchHealth, type CaseRow } from "@/lib/api";
import { classPill, STATE_COLORS, rupees } from "@/lib/format";
import { CaseLink, Card, Failed, Loading, Page, Pill } from "@/components/ui";
import { CasesIcon } from "@/components/icons";
import Select from "@/components/Select";

const STATES = ["", "RECOVERED", "EXHAUSTED", "CLOSED"];

// The class and gate lists come from /health rather than from a copy kept
// here. This file used to hold that copy, and when two recovery classes were
// added to the classifier the filter went on offering the old nine — the new
// classes were in the data and unreachable from the UI.
//
// Every gate is offered, including the ones that never fire. An empty result
// for G07 or G10 is the answer to "did the backstops ever catch anything?",
// and leaving them out would hide the question.

/** Blank means "no filter", which reads better as "all" than as an empty row. */
const toOption = (value: string) => ({ value, label: value || "all" });

export default function Cases() {
  const [rows, setRows] = useState<CaseRow[]>([]);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [filters, setFilters] = useState({ state: "", recovery_class: "", arm: "", blocked_by: "" });
  // "" is the no-filter option and is always present, so the dropdowns read
  // "all" rather than being briefly empty while /health is in flight.
  const [classes, setClasses] = useState<string[]>([""]);
  const [gates, setGates] = useState<string[]>([""]);

  useEffect(() => {
    fetchHealth()
      .then((h) => {
        setClasses(["", ...h.catalog.recovery_classes]);
        setGates(["", ...h.catalog.gates]);
      })
      .catch((e: Error) => setError(e.message));
  }, []);

  useEffect(() => {
    const params = Object.fromEntries(
      Object.entries(filters).filter(([, v]) => v),
    );
    fetchCases({ ...params, limit: 100 })
      .then((r) => {
        setRows(r.cases);
        setTotal(r.total);
      })
      .catch((e: Error) => setError(e.message));
  }, [filters]);

  if (error) return <Failed error={error} />;

  return (
    <Page
      crumbs={[{ label: "RecoverOS" }, { label: "Cases", accent: true }]}
      title="Cases"
      subtitle="Ordered by amount at risk — the same order the agent works them in, because a customer's contact budget is finite."
    >
      <div className="flex flex-wrap gap-3 mb-6">
        <Select
          label="State"
          options={STATES.map(toOption)}
          value={filters.state}
          onChange={(v) => setFilters((f) => ({ ...f, state: v }))}
        />
        <Select
          label="Class"
          options={classes.map(toOption)}
          value={filters.recovery_class}
          onChange={(v) => setFilters((f) => ({ ...f, recovery_class: v }))}
        />
        <Select
          label="Arm"
          options={["", "treatment", "control"].map(toOption)}
          value={filters.arm}
          onChange={(v) => setFilters((f) => ({ ...f, arm: v }))}
        />
        <Select
          label="Blocked by gate"
          options={gates.map(toOption)}
          value={filters.blocked_by}
          onChange={(v) => setFilters((f) => ({ ...f, blocked_by: v }))}
        />
      </div>

      <Card title="Every case in the batch" icon={<CasesIcon size={18} />}>
        <div className="text-xs text-[var(--ink-3)] mb-3 font-mono">
          {rows.length} of {total} cases
        </div>
        {rows.length === 0 ? (
          <Loading what="cases" />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-[11px] uppercase tracking-wider text-[var(--ink-3)] border-b border-[var(--line)]">
                  <th className="pb-2 pr-4">Case</th>
                  <th className="pb-2 pr-4">Class</th>
                  <th className="pb-2 pr-4">State</th>
                  <th className="pb-2 pr-4">Arm</th>
                  <th className="pb-2 pr-4 text-right">At risk</th>
                  <th className="pb-2 pr-4 text-right">Touches</th>
                  <th className="pb-2 pr-4 text-right">Spend</th>
                  <th className="pb-2">Why not recovered</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((c) => (
                  <tr
                    key={c.case_id}
                    className="border-b border-[var(--line)] hover:bg-[var(--surface-inset)]"
                  >
                    <td className="py-2 pr-4">
                      <CaseLink id={c.case_id} />
                    </td>
                    <td className="py-2 pr-4">
                      <Pill className={classPill(c.recovery_class)}>
                        {c.recovery_class}
                      </Pill>
                    </td>
                    <td className="py-2 pr-4">
                      <Pill className={STATE_COLORS[c.state]}>{c.state}</Pill>
                    </td>
                    <td className="py-2 pr-4 text-[var(--ink-3)] font-mono text-xs">
                      {c.arm}
                    </td>
                    <td className="py-2 pr-4 text-right font-mono text-[var(--ink)]">
                      {rupees(c.amount_at_risk_paise, 0)}
                    </td>
                    <td className="py-2 pr-4 text-right font-mono text-[var(--ink-2)]">
                      {c.touches_used}
                    </td>
                    <td className="py-2 pr-4 text-right font-mono text-[var(--ink-3)]">
                      {rupees(c.intervention_cost_paise)}
                    </td>
                    <td className="py-2 text-[var(--ink-3)] text-xs max-w-xs truncate">
                      {c.state === "RECOVERED" ? "—" : c.exception_reason}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </Page>
  );
}

