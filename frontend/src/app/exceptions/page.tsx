"use client";

import { useEffect, useState } from "react";

import { fetchExceptions, type ExceptionRow } from "@/lib/api";
import { classPill, rupees, rupeesShort } from "@/lib/format";
import {
  Bar, Callout, Card, Failed, Loading, Page, Pill, Stat,
} from "@/components/ui";
import { AlertIcon, BanIcon, RupeeIcon } from "@/components/icons";

/**
 * The honest exception list.
 *
 * Deliberately a first-class page rather than an appendix. A recovery system
 * that only reports its wins is not reporting.
 */
export default function Exceptions() {
  const [rows, setRows] = useState<ExceptionRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchExceptions()
      .then((r) => setRows(r.exceptions))
      .catch((e: Error) => setError(e.message));
  }, []);

  if (error) return <Failed error={error} />;
  if (!rows) return <Loading what="exceptions" />;

  const totalCases = rows.reduce((s, r) => s + r.count, 0);
  const totalAmount = rows.reduce((s, r) => s + r.amount_paise, 0);
  const maxAmount = Math.max(...rows.map((r) => r.amount_paise), 1);

  return (
    <Page
      crumbs={[{ label: "RecoverOS" }, { label: "Exceptions", accent: true }]}
      title="Exceptions"
      subtitle="Everything the system did not recover, grouped by why, ranked by the money still on the table."
    >
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-6">
        <Stat
          label="Unresolved cases"
          value={String(totalCases)}
          icon={<AlertIcon size={17} />}
        />
        <Stat
          label="Value left on the table"
          value={rupeesShort(totalAmount)}
          tone="warn"
          icon={<RupeeIcon size={17} />}
        />
        <Stat
          label="Distinct reasons"
          value={String(rows.length)}
          tone="muted"
          icon={<BanIcon size={17} />}
        />
      </div>

      <Card
        title="Why each case is still open"
        hint="Ranked by the money still on the table, not by count"
        icon={<AlertIcon size={18} />}
        tone="warn"
      >
        <div className="space-y-5">
          {rows.map((row) => (
            <div key={row.reason} className="border-b border-[var(--line)] pb-5 last:border-0">
              <div className="flex items-start justify-between gap-6 mb-2">
                <p className="text-sm text-[var(--ink)] leading-relaxed">{row.reason}</p>
                <div className="text-right shrink-0">
                  <div className="font-mono text-sm text-[var(--ink)]">
                    {rupees(row.amount_paise, 0)}
                  </div>
                  <div className="text-xs text-[var(--ink-4)]">{row.count} cases</div>
                </div>
              </div>
              <Bar value={row.amount_paise} max={maxAmount} tone="muted" />
              <div className="flex flex-wrap gap-1.5 mt-2.5">
                {Object.entries(row.by_class)
                  .sort((a, b) => b[1] - a[1])
                  .map(([cls, n]) => (
                    <Pill key={cls} className={classPill(cls)}>
                      {cls} ×{n}
                    </Pill>
                  ))}
              </div>
            </div>
          ))}
        </div>

        <Callout>
          Several of these are not failures. A case closed because the customer
          revoked consent, or because the order was already settled, is the
          system working exactly as intended — the money is genuinely
          unrecoverable and chasing it would be worse than losing it. The rows
          worth arguing about are the ones that ran out of attempts or ran out
          of window.
        </Callout>
      </Card>
    </Page>
  );
}
