"use client";

import { useCallback, useEffect, useState } from "react";

import {
  restoreLedger, tamperLedger, verifyLedger, type AuditStatus,
} from "@/lib/api";
import {
  Callout, Card, Failed, Loading, Page, Pill, Stat,
} from "@/components/ui";
import { LedgerIcon, ShieldIcon } from "@/components/icons";

/**
 * Demonstrating the audit trail rather than asserting it.
 *
 * Verify (valid) → rewrite one historical amount → verify again (invalid, and
 * it names the row). An audit trail nobody has seen fail is just a log table.
 *
 * Restoring is part of the demonstration, not a cleanup afterthought: putting
 * the original bytes back makes the chain verify again, which is what shows
 * the detection comes from the content rather than from an "edited" flag. It
 * also keeps the page from being a one-way door — without it the ledger reads
 * BROKEN on every visit from then on.
 */
export default function Audit() {
  const [status, setStatus] = useState<AuditStatus | null>(null);
  const [tampered, setTampered] = useState<{
    event_id: number;
    before: unknown;
    after: unknown;
  } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(() => {
    verifyLedger().then(setStatus).catch((e: Error) => setError(e.message));
  }, []);

  useEffect(refresh, [refresh]);

  async function tamper() {
    setBusy(true);
    try {
      setTampered(await tamperLedger());
      refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function restore() {
    setBusy(true);
    try {
      const result = await restoreLedger();
      setStatus(result.chain);
      setTampered(null);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (error) return <Failed error={error} />;
  if (!status) return <Loading what="ledger" />;

  return (
    <Page
      crumbs={[{ label: "RecoverOS" }, { label: "Audit Ledger", accent: true }]}
      title="Audit Ledger"
      subtitle="Every decision the system made, hash-chained. Each row's hash covers the previous row's hash plus its own content."
      actions={
        // Restore appears only once the chain is actually broken, so the
        // page offers one obvious next step at a time.
        status.valid ? (
          <button
            onClick={tamper}
            disabled={busy}
            className="px-4 py-2 rounded bg-[var(--critical)] hover:bg-[var(--critical)] disabled:bg-[var(--surface-raised)] disabled:text-[var(--ink-3)] text-white text-sm font-medium transition"
          >
            {busy ? "Rewriting…" : "Tamper with a record"}
          </button>
        ) : (
          <button
            onClick={restore}
            disabled={busy}
            className="px-4 py-2 rounded border border-[var(--line-strong)] bg-[var(--surface-raised)] hover:bg-[var(--surface)] disabled:text-[var(--ink-3)] text-[var(--ink)] text-sm font-medium transition"
          >
            {busy ? "Restoring…" : "Restore the record"}
          </button>
        )
      }
    >
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-6">
        <Stat
          label="Events recorded"
          value={status.records.toLocaleString("en-IN")}
          icon={<LedgerIcon size={17} />}
        />
        <Stat
          label="Chain integrity"
          value={status.valid ? "VALID" : "BROKEN"}
          tone={status.valid ? "good" : "bad"}
          icon={<ShieldIcon size={17} />}
        />
        <Stat
          label="Rows that fail verification"
          value={String(status.broken_count)}
          tone={status.broken_count ? "bad" : "default"}
        />
      </div>

      {status.valid ? (
        <Card>
          <p className="text-sm text-[var(--ink)] leading-relaxed">
            All {status.records.toLocaleString("en-IN")} events verify against a
            fresh recomputation from genesis. Nothing has been edited since it
            was written.
          </p>
          <Callout>
            Press <span className="text-[var(--critical)]">Tamper with a record</span> to
            rewrite one recorded amount, the way somebody covering their tracks
            would. Nothing else is touched — the row keeps its stored hash,
            which is exactly why the next verification catches it.
          </Callout>
        </Card>
      ) : (
        <Card>
          <div className="flex items-center gap-3 mb-4">
            <Pill className="text-[var(--critical)] border-[var(--critical)]/30 bg-[var(--critical)]/10">
              tampering detected
            </Pill>
            <span className="text-sm text-[var(--ink)]">
              Event #{status.first_break} does not match its recorded hash.
            </span>
          </div>

          {tampered && (
            <div className="grid sm:grid-cols-2 gap-4 mb-4">
              <div>
                <div className="text-[11px] uppercase tracking-wider text-[var(--ink-3)] mb-1.5">
                  What was recorded
                </div>
                <pre className="text-xs font-mono bg-[var(--surface-inset)] border border-[var(--line)] rounded p-3 overflow-x-auto text-[var(--ink-2)]">
                  {JSON.stringify(tampered.before, null, 2)}
                </pre>
              </div>
              <div>
                <div className="text-[11px] uppercase tracking-wider text-[var(--ink-3)] mb-1.5">
                  What it was changed to
                </div>
                <pre className="text-xs font-mono bg-[var(--surface-inset)] border border-[var(--critical)]/40 rounded p-3 overflow-x-auto text-[var(--critical)]">
                  {JSON.stringify(tampered.after, null, 2)}
                </pre>
              </div>
            </div>
          )}

          <p className="text-sm font-mono text-[var(--ink-3)]">
            broken_at: [{status.broken_at.join(", ")}]
          </p>

          <Callout>
            Verification walks forward from each row&apos;s stored hash, so an
            edited row is named on its own rather than dragging every later row
            into the report. Naming one row says exactly which decision was
            rewritten. Re-run the batch from{" "}
            <span className="text-[var(--treatment)]">Live Batch</span> to rebuild a clean
            chain.
          </Callout>
        </Card>
      )}
    </Page>
  );
}
