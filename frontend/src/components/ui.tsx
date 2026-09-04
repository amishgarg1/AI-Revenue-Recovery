"use client";

import Link from "next/link";
import { ReactNode } from "react";

import { ChevronRightIcon, InfoIcon, TerminalIcon } from "@/components/icons";

/** Shared primitives. Dense, instrument-panel dark, monospace numerals. */

export type Crumb = { label: string; accent?: boolean };

export function Page({
  title,
  kicker,
  crumbs,
  rail,
  subtitle,
  children,
  actions,
}: {
  title: string;
  kicker?: string;
  /** Breadcrumb chips above the title. */
  crumbs?: Crumb[];
  /**
   * The accent rail beside the title block. Independent of `crumbs` — the
   * landing page wants the rail without the chips, and coupling them meant
   * dropping one silently took the other with it.
   */
  rail?: boolean;
  subtitle?: string;
  children: ReactNode;
  actions?: ReactNode;
}) {
  const showRail = rail ?? Boolean(crumbs);
  return (
    <div className="px-8 py-10 lg:px-12 lg:py-12 max-w-[1400px]">
      <header className="mb-9 flex items-start justify-between gap-8 rise">
        <div>
          {crumbs && <Breadcrumb crumbs={crumbs} />}
          {kicker && !crumbs && (
            <div className="text-[10px] uppercase tracking-[0.18em] text-[var(--ink-3)] mb-2 font-mono">
              {kicker}
            </div>
          )}

          <div className={showRail ? "relative pl-5" : undefined}>
            {showRail && (
              <>
                <span
                  className="absolute left-0 top-[7px] w-[5px] h-[5px] rounded-full"
                  style={{ background: "var(--treatment)" }}
                />
                <span
                  className="absolute left-[2px] top-[16px] bottom-1 w-px"
                  style={{
                    background:
                      "linear-gradient(to bottom, var(--treatment), transparent)",
                  }}
                />
              </>
            )}
            <h1 className="display text-[38px] lg:text-[44px] text-[var(--ink)]">
              {title}
            </h1>
            {subtitle && (
              <p className="text-[14.5px] text-[var(--ink-2)] mt-3 max-w-[62ch] leading-relaxed">
                {subtitle}
              </p>
            )}
          </div>
        </div>
        {actions && <div className="shrink-0">{actions}</div>}
      </header>
      {children}
    </div>
  );
}

function Breadcrumb({ crumbs }: { crumbs: Crumb[] }) {
  return (
    <nav aria-label="Breadcrumb" className="flex items-center gap-1.5 mb-3.5">
      {crumbs.map((crumb, i) => (
        <div key={crumb.label} className="flex items-center gap-1.5">
          {i > 0 && (
            <ChevronRightIcon size={11} className="text-[var(--ink-4)]" />
          )}
          <span
            className={`flex items-center gap-2 rounded-md border border-[var(--line)] bg-[var(--surface)] py-1 ${
              i === 0 ? "pl-1 pr-2.5" : "px-2.5"
            }`}
          >
            {i === 0 && (
              <span
                className="flex items-center justify-center w-[18px] h-[18px] rounded bg-[var(--treatment)]/12 border border-[var(--treatment)]/25"
                style={{ color: "var(--treatment)" }}
              >
                <TerminalIcon size={11} />
              </span>
            )}
            <span
              className="font-mono text-[10px] uppercase tracking-[0.14em]"
              style={{
                color: crumb.accent ? "var(--treatment)" : "var(--ink-2)",
              }}
            >
              {crumb.label}
            </span>
          </span>
        </div>
      ))}
    </nav>
  );
}

export function Card({
  title,
  hint,
  children,
  className = "",
  aside,
  icon,
  tone = "accent",
}: {
  title?: string;
  hint?: string;
  children: ReactNode;
  className?: string;
  aside?: ReactNode;
  icon?: ReactNode;
  tone?: keyof typeof TONES;
}) {
  const hex = TONE_HEX[tone];
  return (
    <section
      className={`border border-[var(--line)] rounded-xl card-lift ${className}`}
      style={cardStyle(hex)}
    >
      {title && (
        <div className="px-5 pt-5 pb-4 flex items-start justify-between gap-4">
          <div className="flex items-start gap-3 min-w-0">
            {icon && (
              <IconChip hex={hex} size={34}>
                {icon}
              </IconChip>
            )}
            <div className="min-w-0">
              <h2 className="text-[13px] font-semibold text-[var(--ink)] uppercase tracking-[0.06em] leading-snug">
                {title}
              </h2>
              {hint && (
                <p className="text-[13px] text-[var(--ink-3)] mt-1 leading-relaxed">
                  {hint}
                </p>
              )}
            </div>
          </div>
          {aside && <div className="shrink-0">{aside}</div>}
        </div>
      )}
      <div className={title ? "px-5 pb-5" : "p-5"}>{children}</div>
    </section>
  );
}

/**
 * The inset a chart sits in — one step darker than the card, with its own
 * hairline, so the plot reads as an instrument mounted on the panel rather
 * than as ink floating on it.
 */
export function Panel({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={`rounded-lg border border-[var(--line)] bg-[var(--surface-inset)]/70 p-4 ${className}`}
    >
      {children}
    </div>
  );
}

/**
 * An explanation attached to a figure. These carry most of the honesty on this
 * dashboard — what a number does and does not mean — so they get a container
 * rather than being small grey text nobody reads.
 */
export function Callout({
  children,
  tone = "accent",
}: {
  children: ReactNode;
  tone?: keyof typeof TONES;
}) {
  const hex = TONE_HEX[tone];
  return (
    <div
      className="mt-4 flex items-start gap-3 rounded-lg border border-[var(--line)] bg-[var(--surface-inset)]/60 px-4 py-3"
      style={{ borderLeft: `2px solid ${hex}66` }}
    >
      <span
        className="shrink-0 mt-px inline-flex items-center justify-center w-[22px] h-[22px] rounded-full"
        style={{ color: hex, background: `${hex}1a`, border: `1px solid ${hex}40` }}
      >
        <InfoIcon size={13} />
      </span>
      <div className="text-[13px] text-[var(--ink-2)] leading-relaxed">
        {children}
      </div>
    </div>
  );
}

/** A bordered link chip, for the "methodology →" affordance on a card head. */
export function LinkPill({
  href,
  children,
}: {
  href: string;
  children: ReactNode;
}) {
  return (
    <Link
      href={href}
      className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--line)] bg-[var(--surface)] px-3 py-1.5 text-[12.5px] transition-colors hover:border-[var(--treatment)]/50"
      style={{ color: "var(--treatment)" }}
    >
      {children}
      <ChevronRightIcon size={13} />
    </Link>
  );
}

const TONES = {
  default: "text-[var(--ink)]",
  good: "text-[var(--recovered)]",
  bad: "text-[var(--critical)]",
  warn: "text-[var(--warn)]",
  accent: "text-[var(--treatment)]",
  muted: "text-[var(--ink-2)]",
} as const;

// Hex per tone, so the icon chip and the corner wash can be tinted without a
// second source of truth for the palette.
const TONE_HEX: Record<keyof typeof TONES, string> = {
  default: "#3987e5",
  good: "#199e70",
  bad: "#d03b3b",
  warn: "#fab219",
  accent: "#3987e5",
  muted: "#8b909a",
};

/**
 * A card is tinted by an accent that follows what the number *is* — recovered
 * money is green, refusals amber, integrity blue. The wash is kept to a corner
 * at ~8% so it reads as a family marker and never competes with the figure.
 */
function cardStyle(hex: string): React.CSSProperties {
  return {
    background: `radial-gradient(130% 90% at 0% 0%, ${hex}14 0%, transparent 58%), var(--surface)`,
  };
}

function IconChip({
  hex,
  size = 32,
  children,
}: {
  hex: string;
  size?: number;
  children: ReactNode;
}) {
  return (
    <span
      className="inline-flex items-center justify-center rounded-lg shrink-0"
      style={{
        width: size,
        height: size,
        color: hex,
        background: `${hex}1a`,
        border: `1px solid ${hex}40`,
      }}
    >
      {children}
    </span>
  );
}

export function Stat({
  label,
  value,
  sub,
  tone = "default",
  size = "md",
  icon,
}: {
  label: string;
  value: string;
  sub?: ReactNode;
  tone?: keyof typeof TONES;
  size?: "md" | "lg";
  icon?: ReactNode;
}) {
  const hex = TONE_HEX[tone];
  return (
    <div
      className="border border-[var(--line)] rounded-lg p-5 flex flex-col card-lift"
      style={cardStyle(hex)}
    >
      {icon && (
        <div className="mb-3">
          <IconChip hex={hex}>{icon}</IconChip>
        </div>
      )}
      <div className="text-[10px] uppercase tracking-[0.14em] text-[var(--ink-3)] mb-2.5">
        {label}
      </div>
      <div
        className={`font-mono font-semibold tracking-tight tnum ${TONES[tone]} ${
          size === "lg" ? "text-[34px] leading-none" : "text-[26px] leading-none"
        }`}
      >
        <Figure value={value} />
      </div>
      {sub && (
        <>
          <div className="border-t border-[var(--line)] mt-4 mb-3" />
          <div className="text-xs text-[var(--ink-3)] leading-relaxed">{sub}</div>
        </>
      )}
    </div>
  );
}

/**
 * The one number the page is about. Same anatomy as `Stat`, given room to
 * breathe — and the label sits beside the icon rather than under it, because at
 * this size a stacked label pushes the figure too far down the card.
 */
export function HeroStat({
  label,
  value,
  aside,
  tone = "good",
  icon,
  figure,
  children,
}: {
  label: string;
  value: string;
  aside?: string;
  tone?: keyof typeof TONES;
  icon?: ReactNode;
  /**
   * Optional graphic between the figure and its explanation. The card
   * stretches to match whatever sits beside it, and that space is better
   * spent showing the claim than left empty.
   */
  figure?: ReactNode;
  children?: ReactNode;
}) {
  const hex = TONE_HEX[tone];
  return (
    <div
      className="border border-[var(--line)] rounded-lg p-6 flex flex-col card-lift"
      style={cardStyle(hex)}
    >
      <div className="flex items-center gap-3 mb-5">
        {icon && <IconChip hex={hex}>{icon}</IconChip>}
        <span className="text-[10px] uppercase tracking-[0.14em] text-[var(--ink-3)]">
          {label}
        </span>
      </div>

      <div className={`display-figure text-[64px] lg:text-[76px] ${TONES[tone]}`}>
        <Figure value={value} />
      </div>
      {aside && (
        <div className="text-[13.5px] text-[var(--ink-3)] mt-3">{aside}</div>
      )}

      {figure}

      {children && (
        <>
          {/* mt-auto, not a fixed margin. The card stretches to match the stat
              grid beside it, and a fixed gap left the difference pooled in the
              middle - the figure and its explanation both floating with dead
              space between them. Pinned to the bottom, the space reads as
              breathing room instead. */}
          <div className="border-t border-[var(--line)] mt-auto pt-5" />
          <div className="text-[14px] text-[var(--ink-2)] leading-relaxed">
            {children}
          </div>
        </>
      )}
    </div>
  );
}

/**
 * A figure, set the way a figure should be.
 *
 * "₹18.34 L" and "+14.4 pp" are not strings, they are three or four parts: a
 * sign, a symbol, a number, and a unit. Setting all of them at the same size
 * made the ₹ read as a character in the number and the pp read as more digits,
 * which is why they looked mismatched rather than merely large.
 *
 * The number keeps full size. Everything around it drops and holds back on
 * opacity rather than switching colour: a grey unit beside a green number
 * reads as a separate fact, and the lakh belongs to the number.
 *
 * Anything that does not parse as a figure passes through untouched. The audit
 * card puts the word VALID through this same slot, and "8 of 11 gates" goes
 * through the `sub` line, not here.
 */
export function Figure({ value }: { value: string }) {
  const match = /^([+-]?)\s*(₹?)\s*([\d.,]+)\s*(Cr|L|K|pp|%)?$/.exec(value.trim());
  if (!match) return <>{value}</>;

  const [, sign, symbol, number, unit] = match;
  return (
    <span className="inline-flex items-baseline">
      {sign && <span className="opacity-70">{sign}</span>}
      {/* max(), not a bare ratio. 0.6em is right on a 76px hero figure and
          becomes 7px inside a 12.5px legend, which is not readable. The floor
          keeps small figures legible without flattening large ones. */}
      {symbol && (
        <span
          className="mr-[0.05em] opacity-70"
          style={{ fontSize: "max(0.6em, 11px)" }}
        >
          {symbol}
        </span>
      )}
      <span>{number}</span>
      {unit && (
        <span
          className="ml-[0.14em] opacity-55"
          style={{ fontSize: "max(0.52em, 10px)" }}
        >
          {unit}
        </span>
      )}
    </span>
  );
}

export function Pill({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <span
      className={`inline-block text-[10.5px] font-mono px-1.5 py-0.5 rounded border leading-relaxed ${
        className ||
        "text-[var(--ink-2)] border-[var(--line-strong)] bg-[var(--surface-raised)]"
      }`}
    >
      {children}
    </span>
  );
}

const BAR_TONES = {
  treatment: "var(--treatment)",
  guard: "var(--guard)",
  recovered: "var(--recovered)",
  control: "var(--control)",
  muted: "var(--line-strong)",
} as const;

export function Bar({
  value,
  max,
  tone = "treatment",
}: {
  value: number;
  max: number;
  tone?: keyof typeof BAR_TONES;
}) {
  const width = max > 0 ? Math.max((value / max) * 100, value > 0 ? 1.5 : 0) : 0;
  return (
    <div className="w-full bg-[var(--surface-inset)] rounded-sm h-1.5 overflow-hidden">
      <div
        className="h-1.5 rounded-sm transition-all duration-500"
        style={{ width: `${width}%`, background: BAR_TONES[tone] }}
      />
    </div>
  );
}

export function Loading({ what }: { what: string }) {
  return (
    <div className="px-10 py-16 text-sm text-[var(--ink-3)] font-mono flex items-center gap-3">
      <span className="relative flex w-2 h-2">
        <span
          className="absolute inline-flex w-2 h-2 rounded-full pulse-ring"
          style={{ background: "var(--treatment)" }}
        />
        <span
          className="relative inline-flex w-2 h-2 rounded-full"
          style={{ background: "var(--treatment)" }}
        />
      </span>
      Loading {what}…
    </div>
  );
}

export function Failed({ error }: { error: string }) {
  return (
    <div className="px-10 py-10">
      <div className="border border-[var(--critical)]/40 bg-[var(--critical)]/[0.07] rounded-lg p-5 max-w-2xl">
        <h2 className="text-[var(--critical)] font-semibold mb-2 text-sm">
          Cannot reach the API
        </h2>
        <p className="text-xs text-[var(--ink-3)] font-mono mb-3">{error}</p>
        <p className="text-sm text-[var(--ink-2)] leading-relaxed">
          Start the backend with <code className="text-[var(--ink)]">make api</code>,
          or on a free hosting tier give it a few seconds to wake from cold start
          and reload.
        </p>
      </div>
    </div>
  );
}

export function CaseLink({ id }: { id: string }) {
  return (
    <Link
      href={`/case/${id}`}
      className="font-mono text-[var(--treatment)] hover:underline underline-offset-2"
    >
      {id}
    </Link>
  );
}

