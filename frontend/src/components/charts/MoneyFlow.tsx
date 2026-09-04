"use client";

import Link from "next/link";
import { useState } from "react";

import type { FlowClass } from "@/lib/api";
import { pct, rupeesShort } from "@/lib/format";

/**
 * Where every rupee at risk ended up.
 *
 * One row per recovery class: the amounts in the header line, and a track whose
 * filled part is the share of that class's money that came back. Rows are
 * ordered by amount at risk, which is also the order the agent works them in,
 * so the chart doubles as a picture of its prioritisation.
 *
 * The tracks are full width rather than scaled to the amount. Scaling them made
 * the small classes almost invisible — DEAD reduced to a sliver — and the
 * question this answers is "what share of this lane's money came back", which
 * is a proportion. The absolute amount is on the row, in rupees, where it can
 * be read exactly instead of estimated from a length.
 */
export default function MoneyFlow({ classes }: { classes: FlowClass[] }) {
  const [hover, setHover] = useState<string | null>(null);

  return (
    <div className="space-y-3">
      {classes.map((c) => {
        const recovered =
          c.at_risk_paise > 0 ? c.recovered_paise / c.at_risk_paise : 0;
        const active = hover === null || hover === c.recovery_class;

        return (
          <Link
            key={c.recovery_class}
            href={`/cases?recovery_class=${c.recovery_class}`}
            className="block group"
            onMouseEnter={() => setHover(c.recovery_class)}
            onMouseLeave={() => setHover(null)}
          >
            <div className="flex items-baseline justify-between gap-4 mb-1.5">
              <span className="text-[12.5px] font-mono text-[var(--ink-2)] group-hover:text-[var(--ink)] transition-colors">
                {c.recovery_class}
              </span>
              <span className="text-[12.5px] font-mono text-[var(--ink-3)] tnum shrink-0">
                {rupeesShort(c.recovered_paise)}
                <span className="text-[var(--ink-4)]"> of </span>
                {rupeesShort(c.at_risk_paise)}
                <span className="text-[var(--ink-4)] ml-2">{c.cases} cases</span>
              </span>
            </div>

            <div
              className="relative h-6 rounded-md overflow-hidden border border-[var(--line)] transition-opacity"
              style={{
                background: "var(--surface-inset)",
                opacity: active ? 1 : 0.45,
              }}
            >
              <div
                className="absolute inset-y-0 left-0 rounded-md transition-all duration-500"
                style={{
                  width: `${Math.max(recovered * 100, recovered > 0 ? 2 : 0)}%`,
                  background: "var(--recovered)",
                }}
              />
              <span
                className={`absolute inset-y-0 flex items-center text-[11px] font-mono font-semibold ${
                  recovered > 0.14 ? "left-2.5 text-[#04140d]" : "text-[var(--ink-3)]"
                }`}
                style={
                  recovered > 0.14
                    ? undefined
                    : { left: `calc(${recovered * 100}% + 10px)` }
                }
              >
                {pct(recovered, 0)}
              </span>
            </div>
          </Link>
        );
      })}

      <div className="flex items-center gap-4 pt-1.5 text-[12px] text-[var(--ink-3)]">
        <span className="inline-flex items-center gap-2">
          <span
            className="inline-block w-2.5 h-2.5 rounded-full"
            style={{ background: "var(--recovered)" }}
          />
          recovered
        </span>
        <span className="inline-flex items-center gap-2">
          <span
            className="inline-block w-2.5 h-2.5 rounded-full border border-[var(--line-strong)]"
            style={{ background: "var(--surface-inset)" }}
          />
          still at risk
        </span>
      </div>
    </div>
  );
}
