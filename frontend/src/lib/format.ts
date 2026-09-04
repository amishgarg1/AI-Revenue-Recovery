/**
 * Formatting helpers.
 *
 * Money arrives from the API in paise — integers, never floats — and is only
 * turned into rupees here, at the edge. Keeping currency as integers all the
 * way through means no rounding drift between the dashboard, EVALUATION.md and
 * the ledger.
 */

export function rupees(paise: number | null | undefined, decimals = 2): string {
  const value = (paise ?? 0) / 100;
  return `₹${value.toLocaleString("en-IN", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  })}`;
}

/** Compact Indian notation for headline tiles: ₹1.06 Cr, ₹4.2 L, ₹8,400. */
export function rupeesShort(paise: number | null | undefined): string {
  const value = (paise ?? 0) / 100;
  if (Math.abs(value) >= 1e7) return `₹${(value / 1e7).toFixed(2)} Cr`;
  if (Math.abs(value) >= 1e5) return `₹${(value / 1e5).toFixed(2)} L`;
  if (Math.abs(value) >= 1e3) return `₹${(value / 1e3).toFixed(1)}K`;
  return `₹${value.toFixed(0)}`;
}

export function pct(fraction: number | null | undefined, decimals = 1): string {
  return `${((fraction ?? 0) * 100).toFixed(decimals)}%`;
}

export function pp(fraction: number | null | undefined, decimals = 1): string {
  const value = (fraction ?? 0) * 100;
  return `${value >= 0 ? "+" : ""}${value.toFixed(decimals)} pp`;
}

export function istTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("en-IN", {
    timeZone: "Asia/Kolkata",
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

/**
 * Recovery-class pills are neutral, on purpose.
 *
 * They used to carry a hue each — nine saturated colours across the app, which
 * is a rainbow palette by any other name. The colour was doing no work: the
 * class name is written inside the pill, nobody compares two classes by hue,
 * and the encoding was never referenced by a legend. It just made every screen
 * look busier than the data was.
 *
 * Colour is kept for things that are genuinely a status — a case's state, a
 * gate's verdict, money recovered — where it means something and there are few
 * enough values to hold in your head.
 */
export const CLASS_PILL =
  "text-[var(--ink-2)] border-[var(--line-strong)] bg-[var(--surface-raised)]";

/** DEAD is the one class worth muting further: it is the end of the line. */
export const CLASS_PILL_MUTED =
  "text-[var(--ink-4)] border-[var(--line)] bg-[var(--surface-inset)]";

export function classPill(recoveryClass: string | null | undefined): string {
  return recoveryClass === "DEAD" ? CLASS_PILL_MUTED : CLASS_PILL;
}

/**
 * State keeps its colour, because state is a status and there are five of them.
 * Three carry a hue and two do not: recovered is the outcome worth seeing,
 * promised is a commitment with a deadline, open is still in play. Exhausted
 * and closed are endings — they should recede, not compete.
 *
 * Drawn from the palette tokens rather than raw Tailwind, so a theme change
 * moves them with everything else.
 */
export const STATE_COLORS: Record<string, string> = {
  RECOVERED:
    "text-[var(--recovered)] border-[var(--recovered)]/30 bg-[var(--recovered)]/10",
  PROMISED: "text-[var(--warn)] border-[var(--warn)]/30 bg-[var(--warn)]/10",
  OPEN:
    "text-[var(--treatment)] border-[var(--treatment)]/30 bg-[var(--treatment)]/10",
  EXHAUSTED: "text-[var(--ink-2)] border-[var(--line-strong)] bg-[var(--surface-raised)]",
  CLOSED: "text-[var(--ink-4)] border-[var(--line)] bg-[var(--surface-inset)]",
};

export const CHANNEL_LABELS: Record<string, string> = {
  silent: "Silent retry",
  whatsapp: "WhatsApp",
  sms: "SMS",
  email: "Email",
  voice: "Voice call",
  human: "Human queue",
};
