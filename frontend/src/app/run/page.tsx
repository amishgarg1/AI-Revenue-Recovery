"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { fetchHealth, streamBatch, type BatchEvent } from "@/lib/api";
import { CHANNEL_LABELS, istTime, rupeesShort } from "@/lib/format";
import { Bar, Callout, Card, Page, Pill, Stat } from "@/components/ui";
import {
  ActivityIcon, RupeeIcon, ShieldAlertIcon, TerminalIcon, TrendingUpIcon,
} from "@/components/icons";

interface Counters {
  tick: number;
  at: string;
  istHour: number;
  sent: number;
  blocked: number;
  recovered: number;
  recoveredPaise: number;
}

const EMPTY: Counters = {
  tick: -1,
  at: "",
  istHour: 0,
  sent: 0,
  blocked: 0,
  recovered: 0,
  recoveredPaise: 0,
};

const FEED_LIMIT = 60;

type FeedItem = {
  id: number;
  kind: "sent" | "blocked" | "recovered";
  text: string;
  detail: string;
};

export default function LiveBatch() {
  const [running, setRunning] = useState(false);
  const [counters, setCounters] = useState<Counters>(EMPTY);
  const [feed, setFeed] = useState<FeedItem[]>([]);
  const [gates, setGates] = useState<Record<string, number>>({});
  const [degraded, setDegraded] = useState<string[]>([]);
  const [total, setTotal] = useState(0);
  const [summary, setSummary] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState<string | null>(null);

  // The horizon is the clock's, not ours. Hardcoding 84 here meant the
  // progress bar silently lied the moment the simulation's length changed.
  const [tickCount, setTickCount] = useState<number | null>(null);

  const sourceRef = useRef<EventSource | null>(null);
  const seq = useRef(0);

  useEffect(() => {
    fetchHealth()
      .then((h) => setTickCount(h.simulation.ticks))
      .catch(() => {
        /* the batch still streams; only the progress bar needs this */
      });
  }, []);

  // An SSE connection left open after unmount keeps a batch running against a
  // browser that stopped listening.
  useEffect(() => () => sourceRef.current?.close(), []);

  const handle = useCallback((event: BatchEvent) => {
    switch (event.type) {
      case "prepared":
        setTotal(event.cases);
        break;
      case "detector":
        setDegraded(event.degraded);
        break;
      case "tick":
        setCounters((c) => ({
          ...c,
          tick: event.tick,
          at: event.at,
          istHour: event.ist_hour,
          sent: event.sent,
          blocked: event.blocked,
          recovered: event.recovered,
        }));
        break;
      case "sent":
        push({
          kind: "sent",
          text: event.case,
          detail: `tier ${event.tier} · ${CHANNEL_LABELS[event.channel] ?? event.channel}`,
        });
        break;
      case "blocked":
        setGates((g) => ({ ...g, [event.gate]: (g[event.gate] ?? 0) + 1 }));
        push({
          kind: "blocked",
          text: event.case,
          detail: `${event.gate} · ${event.reason}`,
        });
        break;
      case "recovered":
        setCounters((c) => ({
          ...c,
          recoveredPaise: c.recoveredPaise + event.amount_paise,
        }));
        push({
          kind: "recovered",
          text: event.case,
          detail: rupeesShort(event.amount_paise),
        });
        break;
      case "done":
        setSummary(event.summary);
        setRunning(false);
        sourceRef.current?.close();
        break;
      case "error":
        setError(event.message);
        setRunning(false);
        sourceRef.current?.close();
        break;
    }

    function push(item: Omit<FeedItem, "id">) {
      setFeed((f) => [{ id: seq.current++, ...item }, ...f].slice(0, FEED_LIMIT));
    }
  }, []);

  function start() {
    setRunning(true);
    setCounters(EMPTY);
    setFeed([]);
    setGates({});
    setSummary(null);
    setError(null);
    sourceRef.current?.close();
    sourceRef.current = streamBatch(handle);
  }

  const progress =
    counters.tick >= 0 && tickCount
      ? ((counters.tick + 1) / tickCount) * 100
      : 0;
  const quiet = counters.istHour >= 21 || counters.istHour < 9;

  return (
    <Page
      crumbs={[{ label: "RecoverOS" }, { label: "Live Batch", accent: true }]}
      title="Live Batch"
      subtitle="Seven simulated days in two-hour ticks. Watch the ladder escalate and the guardrails refuse."
      actions={
        <button
          onClick={start}
          disabled={running}
          className="px-4 py-2 rounded bg-[var(--treatment)] hover:bg-[var(--treatment)] disabled:bg-[var(--surface-raised)] disabled:text-[var(--ink-3)] text-white text-sm font-medium transition"
        >
          {running ? "Running…" : "Run batch"}
        </button>
      }
    >
      {error && (
        <div className="mb-6 border border-[var(--critical)]/40 bg-[var(--critical)]/[0.08] rounded-lg p-4 text-sm text-[var(--critical)] font-mono">
          {error}
        </div>
      )}

      <div className="mb-6">
        <div className="flex justify-between text-xs font-mono text-[var(--ink-3)] mb-2">
          <span>
            {counters.tick >= 0
              ? `tick ${counters.tick + 1}/84 · ${istTime(counters.at)} IST`
              : "idle"}
            {quiet && counters.tick >= 0 && (
              <span className="text-[var(--warn)] ml-2">quiet hours</span>
            )}
          </span>
          <span>{total > 0 && `${total} cases`}</span>
        </div>
        <Bar value={progress} max={100} tone={running ? "treatment" : "recovered"} />
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
        <Stat
          label="Sent"
          value={String(counters.sent)}
          tone="accent"
          icon={<ActivityIcon size={17} />}
        />
        <Stat
          label="Blocked by a gate"
          value={String(counters.blocked)}
          tone="warn"
          icon={<ShieldAlertIcon size={17} />}
        />
        <Stat
          label="Recovered"
          value={String(counters.recovered)}
          tone="good"
          icon={<TrendingUpIcon size={17} />}
        />
        <Stat
          label="Recovered value"
          value={rupeesShort(counters.recoveredPaise)}
          tone="good"
          icon={<RupeeIcon size={17} />}
        />
      </div>

      {degraded.length > 0 && (
        <div className="mb-6 px-4 py-3 rounded border border-[var(--warn)]/35 bg-[var(--warn)]/[0.07] text-sm text-[var(--warn)]">
          Detector flagged {degraded.join(", ")} as degraded before the first
          tick. Silent retries against it are being held, not spent.
        </div>
      )}

      <div className="grid lg:grid-cols-3 gap-6">
        <Card
          title="Decision feed"
          hint="Every send and every refusal, as it happens"
          icon={<TerminalIcon size={18} />}
          className="lg:col-span-2"
        >
          <div className="h-[420px] overflow-y-auto font-mono text-xs space-y-1">
            {feed.length === 0 && (
              <p className="text-[var(--ink-4)]">
                Press “Run batch” to watch decisions stream in.
              </p>
            )}
            {feed.map((item) => (
              <div
                key={item.id}
                className="flex items-center gap-3 px-2 py-1.5 rounded hover:bg-[var(--surface-raised)]"
              >
                <span
                  className={`w-16 shrink-0 uppercase tracking-wide ${
                    item.kind === "blocked"
                      ? "text-[var(--warn)]"
                      : item.kind === "recovered"
                        ? "text-[var(--recovered)]"
                        : "text-[var(--treatment)]"
                  }`}
                >
                  {item.kind}
                </span>
                <span className="text-[var(--ink-2)] w-24 shrink-0">{item.text}</span>
                <span className="text-[var(--ink-3)]">{item.detail}</span>
              </div>
            ))}
          </div>
        </Card>

        <Card
          title="Gates firing"
          hint="Distinct cases refused, by gate"
          icon={<ShieldAlertIcon size={18} />}
          tone="warn"
        >
          {Object.keys(gates).length === 0 ? (
            <p className="text-sm text-[var(--ink-4)]">Nothing refused yet.</p>
          ) : (
            <div className="space-y-2.5">
              {Object.entries(gates)
                .sort((a, b) => b[1] - a[1])
                .map(([gate, n]) => (
                  <div key={gate}>
                    <div className="flex justify-between text-xs font-mono mb-1">
                      <span className="text-[var(--ink-2)]">{gate}</span>
                      <span className="text-[var(--ink)]">{n}</span>
                    </div>
                    <Bar
                      value={n}
                      max={Math.max(...Object.values(gates))}
                      tone="guard"
                    />
                  </div>
                ))}
            </div>
          )}
          <Callout>
            Each case is counted once per distinct refusal reason, so a case
            held overnight by quiet hours does not inflate the count on every
            tick.
          </Callout>
        </Card>
      </div>

      {summary && (
        <Card
          title="Run summary"
          icon={<ActivityIcon size={18} />}
          className="mt-6"
        >
          <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-4 text-sm">
            <SummaryFigure
              label="Spend"
              value={rupeesShort(
                Number((summary.stats as Record<string, number>)?.spend_paise ?? 0),
              )}
            />
            <SummaryFigure
              label="Spend avoided by gates"
              value={rupeesShort(Number(summary.value_protected_paise ?? 0))}
            />
            <SummaryFigure
              label="Compliance exposure avoided"
              value={rupeesShort(
                Number(summary.compliance_risk_avoided_paise ?? 0),
              )}
            />
            <SummaryFigure
              label="Live Razorpay links"
              value={String(summary.real_payment_links ?? 0)}
            />
          </div>
          <div className="mt-4 flex flex-wrap gap-2">
            {Object.entries(
              (summary.gate_blocks as Record<string, number>) ?? {},
            )
              .sort((a, b) => b[1] - a[1])
              .map(([reason, n]) => (
                <Pill key={reason}>
                  {reason} ×{n}
                </Pill>
              ))}
          </div>
        </Card>
      )}
    </Page>
  );
}

function SummaryFigure({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[11px] uppercase tracking-wider text-[var(--ink-3)] mb-1">
        {label}
      </div>
      <div className="font-mono text-[var(--ink)]">{value}</div>
    </div>
  );
}
