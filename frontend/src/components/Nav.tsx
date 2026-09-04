"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import type { ComponentType } from "react";

import {
  ActivityIcon,
  BanIcon,
  AlertIcon,
  BarsIcon,
  CasesIcon,
  ChevronRightIcon,
  FlaskIcon,
  LedgerIcon,
  ShieldIcon, SlidersIcon,
  TerminalIcon, UploadIcon, UserCheckIcon,
} from "@/components/icons";
import Logo from "@/components/Logo";
import { fetchHealth, type HealthStatus } from "@/lib/api";

type IconType = ComponentType<{ className?: string; size?: number }>;

/**
 * Two groups, on purpose. "Result" is what the system claims; "Evidence" is
 * what backs the claim up. A judge should be able to move from one to the other
 * without being told which pages are which.
 */
const GROUPS: { label: string; links: { href: string; label: string; icon: IconType }[] }[] = [
  {
    label: "Result",
    links: [
      { href: "/", label: "Command Center", icon: TerminalIcon },
      { href: "/experiment", label: "Experiment", icon: FlaskIcon },
      { href: "/sensitivity", label: "Sensitivity", icon: SlidersIcon },
      { href: "/exceptions", label: "Exceptions", icon: AlertIcon },
    ],
  },
  {
    label: "Evidence",
    links: [
      { href: "/run", label: "Live Batch", icon: ActivityIcon },
      { href: "/cases", label: "Cases", icon: CasesIcon },
      { href: "/plan", label: "Plan a Backlog", icon: UploadIcon },
      { href: "/queue", label: "Review Queue", icon: UserCheckIcon },
      { href: "/guardrails", label: "Guardrails", icon: ShieldIcon },
      { href: "/validator", label: "LLM Guardrail", icon: BanIcon },
      { href: "/audit", label: "Audit Ledger", icon: LedgerIcon },
    ],
  },
];

// Identity markers, not status. Each service gets a stable colour so the rows
// are scannable; whether it is actually connected is the dot on the right.
const SERVICE_DOT: Record<string, string> = {
  Razorpay: "#22c55e",
  LLM: "#a855f7",
  "Voice TTS": "#eab308",
};

export default function Nav() {
  const pathname = usePathname();
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [down, setDown] = useState(false);

  useEffect(() => {
    fetchHealth().then(setHealth).catch(() => setDown(true));
  }, []);

  return (
    // Flush against the page, square edges, sharing the border with the content
    // area — a floating rounded card read as a separate application sitting
    // next to the dashboard rather than part of it.
    <aside className="w-[212px] shrink-0 border-r border-[var(--line)] bg-[var(--surface)]">
      <div className="h-full flex flex-col overflow-hidden">
        <div className="px-4 pt-5 pb-4">
          <Link href="/" className="block">
            <div className="flex items-center gap-2.5">
              <Logo size={24} />
              <h1 className="text-[18px] font-bold tracking-tight text-[var(--ink)] leading-none">
                Recover<span style={{ color: "var(--treatment)" }}>OS</span>
              </h1>
            </div>
            <p className="mt-2.5 font-mono text-[9px] uppercase tracking-[0.14em] text-[var(--ink-4)] leading-[1.7]">
              The LLM never
              <br />
              touches a rupee
            </p>
          </Link>
        </div>

        <div className="mx-4 border-t border-[var(--line)]" />

        <nav className="flex-1 overflow-y-auto py-3.5">
          {GROUPS.map((group, gi) => (
            <div key={group.label} className={gi > 0 ? "mt-3.5" : ""}>
              {gi > 0 && <div className="mx-4 mb-3.5 border-t border-[var(--line)]" />}

              <div className="flex items-center gap-2 px-4 mb-1.5">
                <span
                  className="w-1 h-1 rounded-full shrink-0"
                  style={{ background: "var(--treatment)" }}
                />
                <span className="font-mono text-[9px] uppercase tracking-[0.2em] text-[var(--ink-3)]">
                  {group.label}
                </span>
              </div>

              <div className="space-y-px">
                {group.links.map((link) => {
                  const active =
                    link.href === "/"
                      ? pathname === "/"
                      : pathname.startsWith(link.href);
                  const Icon = link.icon;

                  return (
                    <div key={link.href} className="relative">
                      {/* The rail sits flush to the panel edge, outside the card */}
                      {active && (
                        <span
                          className="absolute left-0 top-0.5 bottom-0.5 w-0.5 rounded-r-full"
                          style={{ background: "var(--treatment)" }}
                        />
                      )}
                      <Link
                        href={link.href}
                        aria-current={active ? "page" : undefined}
                        className={`ml-1.5 mr-2 flex items-center gap-2.5 rounded-md pl-1.5 pr-2 py-1 transition-colors ${
                          active
                            ? "bg-[var(--surface-raised)] border border-[var(--line-strong)]"
                            : "border border-transparent hover:bg-[var(--surface-raised)]/50"
                        }`}
                      >
                        <span
                          className={`shrink-0 flex items-center justify-center rounded w-7 h-7 ${
                            active
                              ? "bg-[var(--treatment)]/12 border border-[var(--treatment)]/25"
                              : ""
                          }`}
                          style={{
                            color: active ? "var(--treatment)" : "var(--ink-3)",
                          }}
                        >
                          <Icon size={active ? 15 : 16} />
                        </span>

                        <span
                          className={`text-[12.5px] leading-none whitespace-nowrap ${
                            active
                              ? "text-[var(--ink)] font-medium"
                              : "text-[var(--ink-2)]"
                          }`}
                        >
                          {link.label}
                        </span>

                        {active && (
                          <ChevronRightIcon
                            className="ml-auto shrink-0"
                            size={12}
                          />
                        )}
                      </Link>
                    </div>
                  );
                })}
              </div>
            </div>
          ))}
        </nav>

        {/*
          Says out loud which integrations are actually connected. A viewer
          should be able to tell whether the payment links and message bodies on
          screen came from live services or from the deterministic fallbacks,
          without taking the README's word for it.
        */}
        <div className="px-2.5 pb-2.5 space-y-2">
          {down && (
            <div className="rounded-md border border-[var(--critical)]/40 bg-[var(--critical)]/[0.07] px-3 py-2 text-[11.5px] text-[var(--critical)]">
              API unreachable
            </div>
          )}

          {health && (
            <>
              <div className="rounded-md border border-[var(--line)] bg-[var(--surface-inset)]/50 px-3 py-2.5 space-y-2">
                <Integration label="Razorpay" on={health.integrations.razorpay_test_mode} />
                <Integration label="LLM" on={health.integrations.llm} />
                <Integration label="Voice TTS" on={health.integrations.voice_tts} />
              </div>

              <div className="rounded-md border border-[var(--line)] bg-[var(--surface-inset)]/50 px-3 py-2.5 flex items-center gap-2 text-[11.5px]">
                <span className="shrink-0" style={{ color: "var(--treatment)" }}>
                  <BarsIcon size={13} />
                </span>
                <span className="tnum">
                  <span style={{ color: "var(--treatment)" }} className="font-medium">
                    {health.data.cases}
                  </span>
                  <span className="text-[var(--ink-3)]"> cases</span>
                </span>
                <span className="text-[var(--ink-4)]">·</span>
                <span className="tnum">
                  <span style={{ color: "var(--treatment)" }} className="font-medium">
                    {health.data.events}
                  </span>
                  <span className="text-[var(--ink-3)]"> events</span>
                </span>
              </div>
            </>
          )}
        </div>
      </div>
    </aside>
  );
}

function Integration({ label, on }: { label: string; on: boolean }) {
  return (
    <div className="flex items-center gap-2 text-[11.5px]">
      <span
        className="w-1.5 h-1.5 rounded-full shrink-0"
        style={{ background: SERVICE_DOT[label] ?? "var(--ink-3)" }}
      />
      <span className="text-[var(--ink-2)]">{label}</span>

      <span className="ml-auto flex items-center gap-2">
        <span className="w-px h-3 bg-[var(--line-strong)]" />
        <span className="text-[var(--ink-3)]">{on ? "live" : "fallback"}</span>
        {/*
          The state dot follows the state. Green here regardless would say the
          integrations are connected when they are not, which is the one thing
          this panel exists to be straight about.
        */}
        <span
          className="w-1.5 h-1.5 rounded-full shrink-0"
          style={{ background: on ? "var(--good)" : "var(--ink-4)" }}
          title={on ? "connected" : "not configured — using deterministic fallback"}
        />
      </span>
    </div>
  );
}
