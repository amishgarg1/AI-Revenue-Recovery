"use client";

import { pp } from "@/lib/format";

/**
 * How far each assumption can move the answer.
 *
 * A tornado is the right shape here because the question is comparative: not
 * "how uncertain is the lift" but "which of these seventy-three numbers should
 * I argue with first". Bars are ordered by swing and share one axis, so the
 * top bar being four times the second is visible rather than arithmetic.
 *
 * The committed lift is a vertical rule rather than a zero line. Zero is not
 * the interesting reference — the reference is the number we published, and
 * every bar says how far that could have been from where it sits.
 */

export interface TornadoRow {
  label: string;
  low_lift: number;
  high_lift: number;
  swing_pp: number;
  impact: string;
  breaking_point?: number | null;
}

const IMPACT_TONE: Record<string, string> = {
  material: "var(--treatment)",
  moderate: "var(--ink-3)",
  negligible: "var(--line-strong)",
};

export default function Tornado({
  rows,
  committed,
  max = 10,
}: {
  rows: TornadoRow[];
  committed: number;
  max?: number;
}) {
  const shown = rows.slice(0, max);
  if (!shown.length) return null;

  // One shared domain across every bar, padded so the widest does not touch
  // the edge. Per-bar scaling would make a 0.2pp swing look like a 27pp one.
  const lo = Math.min(committed, ...shown.map((r) => r.low_lift));
  const hi = Math.max(committed, ...shown.map((r) => r.high_lift));
  const pad = (hi - lo) * 0.06 || 0.01;
  const domain = [lo - pad, hi + pad];
  const span = domain[1] - domain[0];

  const x = (v: number) => ((v - domain[0]) / span) * 100;
  const committedX = x(committed);

  return (
    <div>
      <div className="relative">
        {/* The published figure, as the reference every bar is read against. */}
        <div
          className="absolute top-0 bottom-6 w-px bg-[var(--ink-3)] z-10"
          style={{ left: `${committedX}%` }}
          aria-hidden
        />

        <ul className="space-y-2 m-0 p-0 list-none">
          {shown.map((row) => {
            const left = x(row.low_lift);
            const width = Math.max(x(row.high_lift) - left, 0.6);
            return (
              <li key={row.label} className="grid grid-cols-[190px_1fr_58px] gap-3 items-center">
                <span
                  className="text-[11.5px] text-[var(--ink-2)] truncate font-mono"
                  title={row.label}
                >
                  {row.label}
                </span>

                <span className="relative h-[18px] block">
                  <span
                    className="absolute inset-y-0 rounded-[2px]"
                    style={{
                      left: `${left}%`,
                      width: `${width}%`,
                      background: IMPACT_TONE[row.impact] ?? "var(--ink-3)",
                      opacity: row.impact === "material" ? 0.85 : 0.5,
                    }}
                  />
                </span>

                <span className="text-[11.5px] text-[var(--ink-3)] tnum text-right font-mono">
                  {row.swing_pp.toFixed(1)}
                </span>
              </li>
            );
          })}
        </ul>

        <div className="grid grid-cols-[190px_1fr_58px] gap-3 mt-2">
          <span />
          <span className="relative block h-4">
            <span
              className="absolute text-[10px] text-[var(--ink-3)] font-mono -translate-x-1/2 whitespace-nowrap"
              style={{ left: `${committedX}%` }}
            >
              published {pp(committed)}
            </span>
          </span>
          <span className="text-[10px] text-[var(--ink-3)] font-mono text-right">
            pp
          </span>
        </div>
      </div>

      <p className="text-[12px] text-[var(--ink-3)] mt-5 leading-relaxed">
        Each bar is the range the net lift moves through as that one assumption
        is swept from 40% to 200% of the value we chose. Everything else is held
        at its committed value. Ordered by swing, so the top row is the number
        worth arguing about.
      </p>
    </div>
  );
}
