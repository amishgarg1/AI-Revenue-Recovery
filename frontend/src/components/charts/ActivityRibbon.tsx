"use client";

import { useMemo, useRef, useState } from "react";

import type { TimelineRow } from "@/lib/api";
import { istTime } from "@/lib/format";
import { Panel } from "@/components/ui";
import { CursorIcon } from "@/components/icons";

/**
 * Seven days of the agent's working rhythm, one bar per two-hour tick.
 *
 * Sends above the axis, refusals below. The shape is the argument: activity
 * collapses to nothing every night because the quiet-hours gate suppresses it,
 * and the refusal band is thickest in the first day when the issuer is still
 * degraded and the frequency caps are saturated.
 *
 * **One scale, both directions.** An earlier version normalised sends and
 * refusals against their own maxima, which is a dual-axis chart wearing a
 * disguise: a tick with 12 sends and 12 refusals drew two bars of different
 * lengths. They now share a single axis, so the halves are comparable and the
 * numbers on the left mean the same thing above and below zero.
 */

const W = 900;
const H = 210;
const PAD = { top: 26, right: 10, bottom: 26, left: 44 };
const GAP = 1.5; // surface gap between adjacent bars

export default function ActivityRibbon({ rows }: { rows: TimelineRow[] }) {
  const svgRef = useRef<SVGSVGElement>(null);
  const [hover, setHover] = useState<number | null>(null);

  const { axisMax, ticks } = useMemo(() => {
    const peak = Math.max(
      ...rows.map((r) => r.sent),
      ...rows.map((r) => r.blocked),
      1,
    );
    // Round out to a readable step so the labels are 40s and 80s, not 73s.
    const step = peak > 120 ? 50 : peak > 60 ? 40 : peak > 24 ? 20 : 10;
    const max = Math.ceil(peak / step) * step;
    return { axisMax: max, ticks: [-max, -max / 2, 0, max / 2, max] };
  }, [rows]);

  if (rows.length === 0) return null;

  const plotW = W - PAD.left - PAD.right;
  const plotH = H - PAD.top - PAD.bottom;
  const mid = PAD.top + plotH / 2;
  const half = plotH / 2;
  const bw = plotW / rows.length;
  const x = (i: number) => PAD.left + i * bw;
  const y = (v: number) => mid - (v / axisMax) * half;

  const h = hover;

  return (
    <figure className="m-0">
      <Panel>
        <div className="flex items-center gap-5 mb-3 text-[12.5px] text-[var(--ink-2)]">
          <span className="inline-flex items-center gap-2">
            <span
              className="w-2.5 h-2.5 rounded-full"
              style={{ background: "var(--treatment)" }}
            />
            Sent
          </span>
          <span className="inline-flex items-center gap-2">
            <span
              className="w-2.5 h-2.5 rounded-full"
              style={{ background: "var(--guard)" }}
            />
            Refused
          </span>
        </div>

        <svg
          ref={svgRef}
          viewBox={`0 0 ${W} ${H}`}
          className="w-full h-auto"
          onMouseLeave={() => setHover(null)}
          role="img"
          aria-label="Messages sent and actions refused, per two-hour tick across seven days."
        >
          {/* Night shading, behind everything */}
          {rows.map((r, i) =>
            r.quiet ? (
              <rect
                key={`q${i}`}
                x={x(i)}
                y={PAD.top}
                width={bw}
                height={plotH}
                fill="var(--plane)"
                opacity={0.5}
              />
            ) : null,
          )}

          {ticks.map((t) => (
            <g key={t}>
              <line
                x1={PAD.left}
                x2={PAD.left + plotW}
                y1={y(t)}
                y2={y(t)}
                stroke={t === 0 ? "var(--axis)" : "var(--grid)"}
                strokeWidth={1}
                strokeDasharray={t === 0 ? undefined : "3 4"}
              />
              <text
                x={PAD.left - 10}
                y={y(t) + 3.5}
                textAnchor="end"
                fontSize={11}
                fontWeight={600}
                fill="var(--ink-2)"
                className="tnum"
              >
                {Math.abs(t)}
              </text>
            </g>
          ))}

          {rows.map((r, i) => (
            <g key={i} onMouseEnter={() => setHover(i)}>
              {/* Hit target spans the full column; the bars are ~8px wide */}
              <rect
                x={x(i)}
                y={PAD.top}
                width={bw}
                height={plotH}
                fill="transparent"
              />
              {r.sent > 0 && (
                <rect
                  x={x(i) + GAP / 2}
                  y={y(r.sent)}
                  width={Math.max(bw - GAP, 1)}
                  height={mid - y(r.sent)}
                  rx={2}
                  fill="var(--treatment)"
                  opacity={h === null || h === i ? 1 : 0.4}
                />
              )}
              {r.blocked > 0 && (
                <rect
                  x={x(i) + GAP / 2}
                  y={mid + 1}
                  width={Math.max(bw - GAP, 1)}
                  height={Math.max(y(-r.blocked) - mid - 1, 1)}
                  rx={2}
                  fill="var(--guard)"
                  opacity={h === null || h === i ? 1 : 0.4}
                />
              )}
            </g>
          ))}

          {rows.map((r, i) =>
            r.tick % 12 === 0 ? (
              <text
                key={`d${i}`}
                x={x(i) + bw / 2}
                y={H - 6}
                textAnchor="middle"
                fontSize={11}
                fontWeight={600}
                fill="var(--ink-2)"
              >
                day {r.day + 1}
              </text>
            ) : null,
          )}

          {h !== null && (
            <line
              x1={x(h) + bw / 2}
              x2={x(h) + bw / 2}
              y1={PAD.top}
              y2={PAD.top + plotH}
              stroke="var(--line-strong)"
              strokeWidth={1}
              pointerEvents="none"
            />
          )}
        </svg>
      </Panel>

      <div className="mt-3 h-5 text-[12.5px] font-mono text-[var(--ink-3)]">
        {h !== null ? (
          <span className="flex flex-wrap gap-x-5">
            <span>{istTime(rows[h].at)} IST</span>
            <span style={{ color: "var(--treatment)" }}>{rows[h].sent} sent</span>
            <span style={{ color: "var(--guard)" }}>{rows[h].blocked} refused</span>
            {rows[h].quiet && (
              <span style={{ color: "var(--warn)" }}>quiet hours</span>
            )}
          </span>
        ) : (
          <span className="inline-flex items-center gap-2">
            <span style={{ color: "var(--treatment)" }}>
              <CursorIcon size={13} />
            </span>
            Hover any tick for its detail.
          </span>
        )}
      </div>
    </figure>
  );
}
