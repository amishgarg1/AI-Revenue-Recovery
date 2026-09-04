"use client";

import { useMemo, useRef, useState } from "react";

import type { TimelineRow, Outage } from "@/lib/api";
import { istTime, pct } from "@/lib/format";
import { Panel } from "@/components/ui";

/**
 * The counterfactual, drawn.
 *
 * Two cumulative recovery curves over the seven-day window: the arm the agent
 * worked, and the arm it never touched. The shaded wedge between them is the
 * incremental lift — the same number the experiment page states, except here
 * you can watch it open up.
 *
 * Plotted as *rates*, not counts. The arms are 578 and 147 cases, so absolute
 * counts would show a gap that is mostly sample size.
 *
 * The vertical bands are not decoration. The dark columns are the nightly
 * quiet-hours windows where the policy engine suppresses all outreach, and the
 * amber band at the start is the issuer outage during which retries were held
 * rather than spent. Both are visible as flat stretches in the treatment
 * curve, which is the most direct evidence that the guardrails are real.
 */

const W = 900;
const H = 300;
const PAD = { top: 16, right: 92, bottom: 28, left: 44 };

export default function DivergenceChart({
  rows,
  outages = [],
  armTotals,
}: {
  rows: TimelineRow[];
  outages?: Outage[];
  armTotals: { treatment: number; control: number };
}) {
  const svgRef = useRef<SVGSVGElement>(null);
  const [hover, setHover] = useState<number | null>(null);

  const { treat, ctrl, yMax, quietBands } = useMemo(() => {
    const t = rows.map((r) =>
      armTotals.treatment ? r.cum_treatment / armTotals.treatment : 0,
    );
    const c = rows.map((r) =>
      armTotals.control ? r.cum_control / armTotals.control : 0,
    );
    const max = Math.max(...t, ...c, 0.05);

    // Merge consecutive quiet ticks into bands so we draw ~7 rects, not 42.
    const bands: { from: number; to: number }[] = [];
    rows.forEach((r, i) => {
      if (!r.quiet) return;
      const last = bands[bands.length - 1];
      if (last && last.to === i - 1) last.to = i;
      else bands.push({ from: i, to: i });
    });

    return {
      treat: t,
      ctrl: c,
      yMax: Math.ceil(max * 20) / 20,
      quietBands: bands,
    };
  }, [rows, armTotals]);

  if (rows.length === 0) return null;

  const plotW = W - PAD.left - PAD.right;
  const plotH = H - PAD.top - PAD.bottom;
  const x = (i: number) => PAD.left + (i / (rows.length - 1)) * plotW;
  const y = (v: number) => PAD.top + plotH - (v / yMax) * plotH;

  const line = (series: number[]) =>
    series.map((v, i) => `${i === 0 ? "M" : "L"}${x(i)},${y(v)}`).join(" ");

  const wedge =
    treat.map((v, i) => `${i === 0 ? "M" : "L"}${x(i)},${y(v)}`).join(" ") +
    " " +
    ctrl
      .map((v, i) => `L${x(ctrl.length - 1 - i)},${y(ctrl[ctrl.length - 1 - i])}`)
      .join(" ") +
    " Z";

  const yTicks = Array.from({ length: 5 }, (_, i) => (yMax / 4) * i);
  const dayTicks = rows
    .map((r, i) => ({ i, day: r.day }))
    .filter(({ i }) => rows[i].tick % 12 === 0);

  const finalTreat = treat[treat.length - 1];
  const finalCtrl = ctrl[ctrl.length - 1];
  const h = hover;

  function onMove(e: React.MouseEvent<SVGSVGElement>) {
    const rect = svgRef.current?.getBoundingClientRect();
    if (!rect) return;
    const px = ((e.clientX - rect.left) / rect.width) * W;
    const idx = Math.round(((px - PAD.left) / plotW) * (rows.length - 1));
    setHover(idx >= 0 && idx < rows.length ? idx : null);
  }

  return (
    <figure className="m-0">
      <Panel>
      <svg
        ref={svgRef}
        viewBox={`0 0 ${W} ${H}`}
        className="w-full h-auto"
        onMouseMove={onMove}
        onMouseLeave={() => setHover(null)}
        role="img"
        aria-label={`Cumulative recovery rate over seven days. Treatment arm reaches ${pct(finalTreat)}, control arm ${pct(finalCtrl)}.`}
      >
        {/* Issuer outage — retries held, not spent */}
        {outages.map((o) => (
          <g key={o.issuer}>
            <rect
              x={x(o.start_tick)}
              y={PAD.top}
              width={Math.max(x(o.end_tick) - x(o.start_tick), 3)}
              height={plotH}
              fill="var(--warn)"
              opacity={0.09}
            />
            <line
              x1={x(o.end_tick)}
              x2={x(o.end_tick)}
              y1={PAD.top}
              y2={PAD.top + plotH}
              stroke="var(--warn)"
              strokeWidth={1}
              strokeDasharray="3 3"
              opacity={0.5}
            />
            <text
              x={x(o.end_tick) + 6}
              y={PAD.top + 12}
              fontSize={10}
              fill="var(--warn)"
              opacity={0.85}
            >
              {o.issuer} recovers
            </text>
          </g>
        ))}

        {/* Grid */}
        {yTicks.map((v) => (
          <g key={v}>
            <line
              x1={PAD.left}
              x2={PAD.left + plotW}
              y1={y(v)}
              y2={y(v)}
              stroke="var(--grid)"
              strokeWidth={1}
            />
            <text
              x={PAD.left - 10}
              y={y(v) + 3.5}
              textAnchor="end"
              fontSize={11}
              fontWeight={600}
              fill="var(--ink-2)"
              className="tnum"
            >
              {Math.round(v * 100)}%
            </text>
          </g>
        ))}

        {dayTicks.map(({ i, day }) => (
          <text
            key={i}
            x={x(i)}
            y={H - 8}
            textAnchor="middle"
            fontSize={11}
            fontWeight={600}
            fill="var(--ink-2)"
          >
            day {day + 1}
          </text>
        ))}

        {/*
          Everything that describes the run is revealed by one sweep, so the
          two arms are seen separating rather than found already apart.
        */}
        <defs>
          <clipPath id="divergence-reveal">
            <rect className="chart-sweep" x={PAD.left} y={0}
                  width={plotW} height="100%" />
          </clipPath>
        </defs>

        <g clipPath="url(#divergence-reveal)">
        {/* The lift, as area */}
        <path d={wedge} fill="var(--treatment)" opacity={0.16} />

        {/*
          Quiet hours, drawn *over* the wedge rather than under it. Underneath,
          the shaded lift washed them out and the nightly no-contact windows —
          the most direct visual evidence that the gate is real — disappeared.
        */}
        {quietBands.map((b, i) => (
          <rect
            key={`q${i}`}
            x={x(b.from)}
            y={PAD.top}
            width={Math.max(x(b.to) - x(b.from), 2)}
            height={plotH}
            fill="var(--plane)"
            opacity={0.42}
          />
        ))}

        {/* Control first, so treatment draws over it */}
        <path
          d={line(ctrl)}
          fill="none"
          stroke="var(--control)"
          strokeWidth={2}
          strokeDasharray="4 3"
        />
        <path
          d={line(treat)}
          fill="none"
          stroke="var(--treatment)"
          strokeWidth={2}
          strokeLinejoin="round"
        />
        </g>

        {/* Direct labels — identity never rests on colour alone */}
        <g>
          <circle cx={x(rows.length - 1)} cy={y(finalTreat)} r={3.5} fill="var(--treatment)" />
          <text
            x={x(rows.length - 1) + 10}
            y={y(finalTreat) - 2}
            fontSize={11}
            fill="var(--ink)"
            fontWeight={600}
            className="tnum"
          >
            {pct(finalTreat)}
          </text>
          <text x={x(rows.length - 1) + 10} y={y(finalTreat) + 11} fontSize={10} fill="var(--ink-3)">
            treated
          </text>
        </g>
        <g>
          <circle cx={x(rows.length - 1)} cy={y(finalCtrl)} r={3.5} fill="var(--control)" />
          <text
            x={x(rows.length - 1) + 10}
            y={y(finalCtrl) - 2}
            fontSize={11}
            fill="var(--ink-2)"
            fontWeight={600}
            className="tnum"
          >
            {pct(finalCtrl)}
          </text>
          <text x={x(rows.length - 1) + 10} y={y(finalCtrl) + 11} fontSize={10} fill="var(--ink-3)">
            untouched
          </text>
        </g>

        {/* Crosshair */}
        {h !== null && (
          <g pointerEvents="none">
            <line
              x1={x(h)}
              x2={x(h)}
              y1={PAD.top}
              y2={PAD.top + plotH}
              stroke="var(--line-strong)"
              strokeWidth={1}
            />
            <circle cx={x(h)} cy={y(treat[h])} r={4} fill="var(--treatment)" stroke="var(--surface)" strokeWidth={2} />
            <circle cx={x(h)} cy={y(ctrl[h])} r={4} fill="var(--control)" stroke="var(--surface)" strokeWidth={2} />
          </g>
        )}
      </svg>
      </Panel>

      <div className="mt-3.5 h-5">
        {h !== null && (
          <div className="flex flex-wrap items-center gap-x-6 gap-y-1 text-[12.5px] font-mono">
            <span className="text-[var(--ink-3)]">{istTime(rows[h].at)} IST</span>
            <span className="text-[var(--ink-2)]">
              <span
                className="inline-block w-2 h-2 rounded-sm mr-1.5 align-middle"
                style={{ background: "var(--treatment)" }}
              />
              treated {pct(treat[h])}
            </span>
            <span className="text-[var(--ink-2)]">
              <span
                className="inline-block w-2 h-2 rounded-sm mr-1.5 align-middle"
                style={{ background: "var(--control)" }}
              />
              untouched {pct(ctrl[h])}
            </span>
            <span className="text-[var(--ink)]">
              gap {((treat[h] - ctrl[h]) * 100).toFixed(1)} pp
            </span>
            {rows[h].quiet && (
              <span className="text-[var(--warn)]">quiet hours — no outreach</span>
            )}
          </div>
        )}
      </div>

      <figcaption className="mt-1 flex flex-wrap items-center gap-x-6 gap-y-2 text-[12.5px] text-[var(--ink-2)]">
        <LegendLine color="var(--treatment)" label="Treatment — worked by the agent" />
        <LegendLine color="var(--control)" label="Control — never contacted" dashed />
        <LegendBand label="Quiet hours (9PM–9AM IST)" />
        <LegendBand label="Issuer degraded, retries held" color="var(--warn)" />
      </figcaption>
    </figure>
  );
}

function LegendLine({
  color,
  label,
  dashed,
}: {
  color: string;
  label: string;
  dashed?: boolean;
}) {
  return (
    <span className="inline-flex items-center gap-2">
      <svg width="26" height="8" aria-hidden="true">
        <line
          x1="1"
          y1="4"
          x2="25"
          y2="4"
          stroke={color}
          strokeWidth="3"
          strokeLinecap="round"
          strokeDasharray={dashed ? "5 3" : undefined}
        />
      </svg>
      {label}
    </span>
  );
}

/** Ring swatches for the shaded regions — they are areas, not lines. */
function LegendBand({ label, color }: { label: string; color?: string }) {
  return (
    <span className="inline-flex items-center gap-2">
      <span
        className="inline-block w-3.5 h-3.5 rounded-full"
        style={{
          background: color ? `${"var(--plane)"}` : "var(--plane)",
          border: `1.5px solid ${color ?? "var(--line-strong)"}`,
        }}
      />
      {label}
    </span>
  );
}
