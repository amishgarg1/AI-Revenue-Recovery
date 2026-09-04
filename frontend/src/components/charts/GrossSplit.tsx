"use client";

import { rupeesShort } from "@/lib/format";
import { Figure } from "@/components/ui";

/**
 * Gross recovery, split into what the agent added and what would have
 * happened anyway.
 *
 * This is the project's central claim and it was carried by a sentence. Two
 * bars say it faster: the grey part is the control arm's natural recovery
 * rate applied to the same money, and it is deliberately the larger-looking
 * half in most runs — the point is that claiming the whole bar would have
 * been the easy lie.
 *
 * The widths are proportions of gross, not of the amount at risk, so the bar
 * answers "of what came back, how much was ours" rather than restating the
 * recovery rate.
 */
export default function GrossSplit({
  gross,
  incremental,
}: {
  gross: number;
  incremental: number;
}) {
  if (gross <= 0) return null;

  const natural = Math.max(gross - incremental, 0);
  const oursPct = (incremental / gross) * 100;

  return (
    <div className="mt-6">
      <div className="flex h-[10px] w-full overflow-hidden rounded-[3px]">
        <div
          className="chart-sweep"
          style={{ width: `${oursPct}%`, background: "var(--recovered)" }}
          title={`Incremental — ${rupeesShort(incremental)}`}
        />
        <div
          className="chart-sweep"
          style={{
            width: `${100 - oursPct}%`,
            background: "var(--control)",
            opacity: 0.42,
          }}
          title={`Would have happened anyway — ${rupeesShort(natural)}`}
        />
      </div>

      <div className="mt-3 flex flex-wrap items-baseline gap-x-6 gap-y-1.5">
        <span className="flex items-baseline gap-2 text-[12.5px]">
          <span
            className="inline-block w-2 h-2 rounded-[2px] shrink-0"
            style={{ background: "var(--recovered)" }}
          />
          <span className="text-[var(--ink-2)]">the agent added</span>
          <span className="font-mono tnum text-[var(--ink)]">
            <Figure value={rupeesShort(incremental)} />
          </span>
        </span>
        <span className="flex items-baseline gap-2 text-[12.5px]">
          <span
            className="inline-block w-2 h-2 rounded-[2px] shrink-0"
            style={{ background: "var(--control)", opacity: 0.42 }}
          />
          <span className="text-[var(--ink-3)]">would have happened anyway</span>
          <span className="font-mono tnum text-[var(--ink-3)]">
            <Figure value={rupeesShort(natural)} />
          </span>
        </span>
      </div>
    </div>
  );
}
