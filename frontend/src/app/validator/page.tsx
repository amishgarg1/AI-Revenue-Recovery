"use client";

import { useCallback, useEffect, useState } from "react";

import { ShieldIcon, TerminalIcon } from "@/components/icons";
import {
  Callout,
  Card,
  CaseLink,
  Failed,
  Loading,
  Page,
  Panel,
  Pill,
} from "@/components/ui";
import {
  fetchLlmSamples,
  validateDraft,
  type LlmSample,
  type ValidationResponse,
} from "@/lib/api";

/**
 * The guardrail, running.
 *
 * "The LLM never touches a rupee" is the project's one architectural claim, and
 * this is the page where it stops being a claim. Pick a draft — or write one —
 * and the real validator, the same function the batch calls, reports every
 * check and shows what would actually have gone out.
 */

const CHECK_LABELS: Record<string, string> = {
  schema: "Valid JSON matching the schema",
  no_literal_numbers: "No literal digits in the body",
  has_amount_token: "{{amount}} present",
  has_link_token: "{{payment_link}} present",
  compliance: "No coercive or legal-threat language",
  length: "Within the channel's length cap",
  channel_valid: "Channel is one we send on",
  channel_match: "Answered for the channel we asked about",
  language: "Answered in the language we asked for",
  voice_disclosure: "Voice script discloses it is automated",
  voice_optout: "Voice script offers an opt-out",
};

export default function Validator() {
  const [samples, setSamples] = useState<LlmSample[]>([]);
  const [banned, setBanned] = useState<string[]>([]);
  const [active, setActive] = useState<LlmSample | null>(null);
  const [body, setBody] = useState("");
  const [result, setResult] = useState<ValidationResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const run = useCallback(
    async (draft: { body: string; channel: string; language: string }) => {
      try {
        setResult(await validateDraft(draft));
      } catch (e) {
        setError((e as Error).message);
      }
    },
    [],
  );

  useEffect(() => {
    fetchLlmSamples()
      .then((r) => {
        setSamples(r.samples);
        setBanned(r.banned_phrases);
        const first = r.samples[1] ?? r.samples[0];
        if (first) {
          setActive(first);
          setBody(first.body);
          void run(first);
        }
      })
      .catch((e: Error) => setError(e.message));
  }, [run]);

  if (error) return <Failed error={error} />;
  if (!active) return <Loading what="validator" />;

  function pick(sample: LlmSample) {
    setActive(sample);
    setBody(sample.body);
    void run(sample);
  }

  return (
    <Page
      title="The guardrail, running"
      subtitle="Every model output passes through this before it can become a message. Pick a draft or write your own — this is the same validator the batch calls, not a demonstration of one."
    >
      <div className="grid lg:grid-cols-[300px_1fr] gap-4">
        <Card title="Drafts a model actually produces" icon={<TerminalIcon size={18} />}>
          <div className="space-y-1">
            {samples.map((s) => {
              const on = active?.id === s.id;
              return (
                <button
                  key={s.id}
                  onClick={() => pick(s)}
                  className={`w-full text-left rounded-lg px-3 py-2.5 border transition-colors ${
                    on
                      ? "bg-[var(--surface-raised)] border-[var(--line-strong)]"
                      : "border-transparent hover:bg-[var(--surface-raised)]/50"
                  }`}
                >
                  <div className="flex items-center gap-2 mb-1">
                    <span
                      className="w-1.5 h-1.5 rounded-full shrink-0"
                      style={{
                        background:
                          s.expect === "pass"
                            ? "var(--recovered)"
                            : "var(--guard)",
                      }}
                    />
                    <span
                      className={`text-[12.5px] ${
                        on ? "text-[var(--ink)]" : "text-[var(--ink-2)]"
                      }`}
                    >
                      {s.label}
                    </span>
                  </div>
                  <p className="text-[11.5px] text-[var(--ink-4)] leading-relaxed pl-3.5">
                    {s.channel} · {s.language}
                  </p>
                </button>
              );
            })}
          </div>
        </Card>

        <div className="space-y-4">
          <Card
            title="The draft"
            hint={active.note}
            icon={<ShieldIcon size={18} />}
            tone={result?.ok ? "good" : "warn"}
          >
            <textarea
              value={body}
              onChange={(e) => setBody(e.target.value)}
              rows={5}
              spellCheck={false}
              className="w-full rounded-lg border border-[var(--line)] bg-[var(--surface-inset)] p-3.5 font-mono text-[13px] text-[var(--ink)] leading-relaxed resize-y focus:outline-none focus:border-[var(--treatment)]/60"
            />
            <div className="flex items-center gap-3 mt-3">
              <button
                onClick={() =>
                  void run({
                    body,
                    channel: active.channel,
                    language: active.language,
                  })
                }
                className="px-4 py-2 rounded-lg text-white text-[13px] font-medium transition-opacity hover:opacity-90"
                style={{ background: "var(--treatment)" }}
              >
                Validate
              </button>
              <span className="text-[12px] text-[var(--ink-4)]">
                Try adding a rupee figure, or the word “police”.
              </span>
            </div>
          </Card>

          {result && (
            <>
              <Card
                title={result.ok ? "Accepted" : `Rejected — ${result.reason}`}
                icon={<ShieldIcon size={18} />}
                tone={result.ok ? "good" : "bad"}
              >
                <div className="grid sm:grid-cols-2 gap-x-6 gap-y-2 mb-4">
                  {Object.entries(result.checks)
                    .filter(([k]) => k in CHECK_LABELS)
                    .map(([key, value]) => (
                      <div key={key} className="flex items-center gap-2.5 text-[13px]">
                        <span
                          className="w-4 h-4 rounded shrink-0 flex items-center justify-center text-[10px] font-bold"
                          style={{
                            background: value
                              ? "var(--recovered)"
                              : "var(--critical)",
                            color: "#0b0b0d",
                          }}
                        >
                          {value ? "✓" : "✕"}
                        </span>
                        <span
                          className={
                            value ? "text-[var(--ink-2)]" : "text-[var(--ink)]"
                          }
                        >
                          {CHECK_LABELS[key]}
                        </span>
                      </div>
                    ))}
                </div>

                <div className="text-[11px] uppercase tracking-[0.14em] text-[var(--ink-3)] mb-2">
                  What would actually be sent
                  {/* Naming the case makes the claim checkable: the figures
                      below are that case's, and you can go and look. */}
                  {result.values_from_case && (
                    <span className="normal-case tracking-normal text-[var(--ink-3)]">
                      {" — values from "}
                      <CaseLink id={result.values_from_case} />
                    </span>
                  )}
                </div>
                <Panel>
                  <p className="text-[13px] text-[var(--ink)] leading-relaxed">
                    {result.would_send}
                  </p>
                  <div className="mt-3">
                    <Pill
                      className={
                        result.used === "llm_template"
                          ? "text-[#9085e9] border-[#9085e9]/30 bg-[#9085e9]/10"
                          : "text-[var(--ink-2)] border-[var(--line-strong)] bg-[var(--surface-raised)]"
                      }
                    >
                      {result.used === "llm_template"
                        ? "the model's template, rendered"
                        : "deterministic fallback"}
                    </Pill>
                  </div>
                </Panel>

                <Callout tone={result.ok ? "good" : "warn"}>
                  {result.ok
                    ? "Every number in that message came from the database. The model supplied the sentence around them and nothing else."
                    : "The draft was discarded and a deterministic template took its place. This is a downgrade, not an outage: the batch does not stop, and nothing the model wrote reaches a customer."}
                </Callout>
              </Card>

              <Card title="What the compliance check looks for">
                <div className="flex flex-wrap gap-1.5">
                  {banned.map((phrase) => (
                    <Pill key={phrase}>{phrase}</Pill>
                  ))}
                </div>
                <Callout>
                  Hindi and Hinglish phrases are on the list alongside the
                  English ones. A debt-collection message that threatens{" "}
                  <span className="font-mono text-[var(--ink-2)]">kanooni
                  karyavahi</span> is exactly as much of a problem as one
                  threatening legal action, and an English-only list would have
                  passed it.
                </Callout>
              </Card>
            </>
          )}
        </div>
      </div>
    </Page>
  );
}
