"use client";

import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { fetchCase, type ActionRow, type CaseDetail, type EventRow } from "@/lib/api";
import {
  CHANNEL_LABELS,
  classPill,
  STATE_COLORS,
  istTime,
  rupees,
} from "@/lib/format";
import {
  Callout, Card, Failed, Loading, Page, Pill,
} from "@/components/ui";
import { AlertIcon, CasesIcon, LedgerIcon } from "@/components/icons";
import AudioPlayer from "@/components/AudioPlayer";

/**
 * One case, from the failed payment to the outcome.
 *
 * This is the page that answers "why did the system do that?" — which rule
 * fired, what all eleven gates thought, what the model drafted, what the
 * validator checked, what went out, and what happened. Nobody has to trust a
 * summary.
 */
export default function CaseTimeline() {
  const { id } = useParams<{ id: string }>();
  const [data, setData] = useState<CaseDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (id) fetchCase(id).then(setData).catch((e: Error) => setError(e.message));
  }, [id]);

  if (error) return <Failed error={error} />;
  if (!data) return <Loading what="case" />;

  const { case: c, customer, payments, actions, events } = data;

  return (
    <Page
      title={c.case_id}
      subtitle={`${c.entity_type} ${c.entity_id} · ${rupees(c.amount_at_risk_paise)} at risk`}
      actions={
        <div className="flex gap-2">
          <Pill className={STATE_COLORS[c.state]}>{c.state}</Pill>
          <Pill className={classPill(c.recovery_class)}>
            {c.recovery_class}
          </Pill>
          <Pill
            className={
              c.arm === "control"
                ? "text-[var(--ink-2)] border-[var(--line-strong)] bg-[var(--surface-raised)]"
                : "text-[var(--treatment)] border-[var(--treatment)]/30 bg-[var(--treatment)]/10"
            }
          >
            {c.arm}
          </Pill>
        </div>
      }
    >
      {c.arm === "control" && (
        <div className="mb-6 px-4 py-3 rounded border border-[var(--line-strong)] bg-[var(--surface-inset)] text-sm text-[var(--ink-2)]">
          This case is in the control arm. It was classified and measured, but
          never contacted and never billed. That is what makes the reported lift
          a measurement rather than a comparison of the system against itself.
        </div>
      )}

      <div className="grid lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 space-y-6">
          {payments.length > 0 && (
            <Card
              title="Why it failed"
              hint="Razorpay's own error taxonomy — the fields the routing decision is built on"
              icon={<AlertIcon size={18} />}
              tone="bad"
            >
              <div className="space-y-3">
                {payments.map((p) => (
                  <div
                    key={p.payment_id}
                    className="border border-[var(--line)] rounded p-3 bg-[var(--surface-inset)]"
                  >
                    <div className="flex items-center justify-between mb-2">
                      <span className="font-mono text-xs text-[var(--ink-2)]">
                        attempt {p.attempt_no} · {p.method} · {p.issuer}
                      </span>
                      <span className="font-mono text-xs text-[var(--ink-3)]">
                        {istTime(p.created_at)}
                      </span>
                    </div>
                    <div className="flex flex-wrap gap-2 mb-2">
                      <Pill className="text-[var(--critical)] border-[var(--critical)]/30 bg-[var(--critical)]/10">
                        {p.error_reason}
                      </Pill>
                      <Pill>source: {p.error_source}</Pill>
                      <Pill>step: {p.error_step}</Pill>
                    </div>
                    <p className="text-sm text-[var(--ink-2)]">{p.error_description}</p>
                  </div>
                ))}
              </div>
              <Callout>
                <span className="text-[var(--ink-2)]">error_source</span> says whose
                fault it was and{" "}
                <span className="text-[var(--ink-2)]">error_step</span> says where it
                broke. Together they decide recoverability — bank or gateway
                means retry, customer means nudge, internal risk means do not
                touch it.
              </Callout>
            </Card>
          )}

          <Card
            title="What happened, in order"
            hint="Every attempt, with all eleven gate verdicts"
            icon={<CasesIcon size={18} />}
          >
            {actions.length === 0 ? (
              <p className="text-sm text-[var(--ink-3)]">
                No action was ever attempted on this case.
                {c.exception_reason && (
                  <span className="block mt-2 text-[var(--ink-2)]">
                    {c.exception_reason}
                  </span>
                )}
              </p>
            ) : (
              <div className="space-y-4">
                {actions.map((a) => (
                  <ActionBlock
                    key={a.action_id}
                    action={a}
                    language={String(customer?.language_pref ?? "en")}
                  />
                ))}
              </div>
            )}
          </Card>

          <Card
            title="Raw ledger"
            hint="Every row hash-chained to the one before it"
            icon={<LedgerIcon size={18} />}
            tone="muted"
          >
            <div className="space-y-1 font-mono text-xs max-h-96 overflow-y-auto">
              {events.map((e) => (
                <LedgerRow key={e.event_id} event={e} />
              ))}
            </div>
          </Card>
        </div>

        <div className="space-y-6">
          <Card title="Outcome">
            <dl className="space-y-3 text-sm">
              <Field label="State" value={c.state} />
              <Field label="Resolution" value={c.resolution ?? "—"} />
              <Field label="Touches used" value={`${c.touches_used} of 3`} />
              <Field label="Spend" value={rupees(c.intervention_cost_paise)} />
              <Field label="Recovered" value={rupees(c.recovered_paise)} />
              {c.promise_date && (
                <Field label="Promised by" value={istTime(c.promise_date)} />
              )}
              {c.rule_id && <Field label="Classifier rule" value={c.rule_id} />}
            </dl>
            {c.exception_reason && (
              <Callout>{c.exception_reason}</Callout>
            )}
          </Card>

          {customer && (
            <Card title="Customer">
              <dl className="space-y-3 text-sm">
                <Field label="Name" value={String(customer.name)} />
                <Field label="Segment" value={String(customer.segment)} />
                <Field label="Language" value={String(customer.language_pref)} />
              </dl>
              <div className="mt-4 flex flex-wrap gap-1.5">
                {(["whatsapp", "sms", "email", "voice"] as const).map((ch) => (
                  <Pill
                    key={ch}
                    className={
                      customer[`consent_${ch}`]
                        ? "text-[var(--recovered)] border-[var(--recovered)]/30 bg-[var(--recovered)]/10"
                        : "text-[var(--ink-4)] border-[var(--line-strong)] bg-[var(--surface-raised)]"
                    }
                  >
                    {ch}
                  </Pill>
                ))}
              </div>
              {Boolean(customer.opted_out_at) && (
                <Callout>
                  This customer opted out on {String(customer.opted_out_at)}.
                  G01 suppresses every channel for them.
                </Callout>
              )}
              {Boolean(customer.dnd_registered) && (
                <Callout>Registered on the national DND list — voice is blocked.</Callout>
              )}
            </Card>
          )}
        </div>
      </div>
    </Page>
  );
}

/**
 * Distinguishes "the model was never asked" from "the model was asked and its
 * answer was refused". Both end in a fallback template, but only one of them
 * is the guardrail doing its job, and conflating them would overstate what the
 * validator caught.
 */
const NEVER_ASKED = ["NO_API_KEY", "LITELLM_NOT_INSTALLED"];

function wasNeverAsked(reason: string): boolean {
  return NEVER_ASKED.includes(reason) || reason.startsWith("PROVIDER_ERROR");
}

function ActionBlock({
  action,
  language,
}: {
  action: ActionRow;
  language: string;
}) {
  const blocked = action.status === "BLOCKED";
  const trail = action.gate_decisions_json ?? [];
  const refusals = trail.filter((g) => !g.allowed);

  return (
    <div
      className={`border rounded p-4 ${
        blocked
          ? "border-[var(--warn)]/35 bg-[var(--warn)]/[0.05]"
          : "border-[var(--line)] bg-[var(--surface-inset)]"
      }`}
    >
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Pill
            className={
              blocked
                ? "text-[var(--warn)] border-[var(--warn)]/30 bg-[var(--warn)]/10"
                : "text-[var(--treatment)] border-[var(--treatment)]/30 bg-[var(--treatment)]/10"
            }
          >
            {action.status}
          </Pill>
          <span className="text-sm text-[var(--ink)]">
            Tier {action.tier} · {CHANNEL_LABELS[action.channel] ?? action.channel}
          </span>
          {!blocked && action.cost_paise > 0 && (
            <span className="text-xs font-mono text-[var(--ink-3)]">
              {rupees(action.cost_paise)}
            </span>
          )}
        </div>
        <span className="text-xs font-mono text-[var(--ink-4)]">
          {action.sent_at ? istTime(action.sent_at) : `tick ${action.tick}`}
        </span>
      </div>

      {/* The full eleven-gate trail, not just the first refusal. */}
      <div className="grid grid-cols-11 gap-1 mb-3">
        {trail.map((g) => (
          <div
            key={g.gate_id}
            title={`${g.gate_id} ${g.name}: ${g.reason_code} — ${g.detail}`}
            className={`h-6 rounded-sm flex items-center justify-center text-[9px] font-mono cursor-help ${
              g.allowed
                ? "bg-[var(--recovered)]/[0.12] text-[var(--recovered)] border border-[var(--recovered)]/30"
                : "bg-[var(--critical)]/[0.12] text-[var(--critical)] border border-[var(--critical)]/50"
            }`}
          >
            {g.gate_id.replace("G", "")}
          </div>
        ))}
      </div>

      {refusals.map((g) => (
        <p key={g.gate_id} className="text-sm text-[var(--warn)] mb-1">
          <span className="font-mono text-xs text-[var(--warn)]">
            {g.gate_id} {g.name}
          </span>{" "}
          — {g.detail}
        </p>
      ))}

      {/*
        A Tier-3 action is a phone call, so its script gets treated as a script:
        shown in full with the keypad options, and played if audio has been
        rendered. Rendering needs a TTS key; the script does not, and it is
        generated, validated and placed by the batch either way.
      */}
      {action.channel === "voice" && action.message_body && (
        <VoiceScript
          body={action.message_body}
          language={language}
          caseId={action.case_id}
        />
      )}

      {action.channel !== "voice" && action.message_body && (
        <div className="mt-3 p-3 rounded bg-[var(--surface-inset)] border border-[var(--line)]">
          <p className="text-sm text-[var(--ink)] leading-relaxed">
            {action.message_body}
          </p>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <Pill
              className={
                action.llm_used
                  ? "text-[#9085e9] border-[#9085e9]/30 bg-[#9085e9]/10"
                  : "text-[var(--ink-2)] border-[var(--line-strong)] bg-[var(--surface-raised)]"
              }
            >
              {action.llm_used ? "LLM template" : "deterministic fallback"}
            </Pill>
            {action.llm_rejected_reason && (
              <Pill
                className={
                  wasNeverAsked(action.llm_rejected_reason)
                    ? "text-[var(--ink-3)] border-[var(--line-strong)] bg-[var(--surface-raised)]"
                    : "text-[var(--critical)] border-[var(--critical)]/30 bg-[var(--critical)]/10"
                }
              >
                {wasNeverAsked(action.llm_rejected_reason)
                  ? `no model call: ${action.llm_rejected_reason}`
                  : `validator: ${action.llm_rejected_reason}`}
              </Pill>
            )}
            {action.payment_link_url && (
              <Pill
                className={
                  action.payment_link_is_real
                    ? "text-[var(--recovered)] border-[var(--recovered)]/30 bg-[var(--recovered)]/10"
                    : "text-[var(--ink-3)] border-[var(--line-strong)] bg-[var(--surface-raised)]"
                }
              >
                {action.payment_link_is_real
                  ? "live Razorpay test link"
                  : "simulated link"}
              </Pill>
            )}
          </div>
          {action.llm_rejected_reason && (
            <Callout>
              {wasNeverAsked(action.llm_rejected_reason)
                ? "No LLM provider is configured in this deployment, so no model was asked and this deterministic template was used. Worth being precise about: nothing was rejected here, because nothing was drafted."
                : "The model's draft failed validation and this deterministic template was used instead. The batch did not stop, and no number the model wrote reached anybody."}
            </Callout>
          )}
        </div>
      )}
    </div>
  );
}

function VoiceScript({
  body,
  language,
  caseId,
}: {
  body: string;
  language: string;
  caseId: string;
}) {
  const [audioOk, setAudioOk] = useState(true);

  // This case's own call, not a specimen. `make voice` renders one clip per
  // placed call from that call's real values, so what is written above and
  // what the speaker says are the same sentence. Sharing one recording across
  // every voice case had the page read one name and the audio say another.
  const src = `/voice/${caseId}.wav`;

  return (
    <div className="mt-3 rounded-lg border border-[var(--line)] bg-[var(--surface-inset)] p-4">
      <div className="flex items-center gap-2 mb-3">
        <Pill className="text-[var(--warn)] border-[var(--warn)]/30 bg-[var(--warn)]/10">
          Voice script · {language}
        </Pill>
        <span className="text-[11px] text-[var(--ink-4)]">
          {body.length} of 400 characters
        </span>
      </div>

      <p className="text-[13px] text-[var(--ink)] leading-relaxed">{body}</p>

      <div className="flex flex-wrap gap-2 mt-3">
        <Pill>1 — confirm a payment date</Pill>
        <Pill>2 — call me later</Pill>
        <Pill className="text-[var(--warn)] border-[var(--warn)]/30 bg-[var(--warn)]/10">
          9 — stop these calls
        </Pill>
      </div>

      {audioOk ? (
        <AudioPlayer src={src} onError={() => setAudioOk(false)} />
      ) : (
        <p className="text-[12px] text-[var(--ink-4)] mt-3.5 leading-relaxed">
          No recording for this call — run{" "}
          <span className="font-mono">make voice</span> with{" "}
          <span className="font-mono">SARVAM_API_KEY</span> set. The script above
          is still generated, validated and placed by the batch; only the
          text-to-speech step is missing. Nothing else is played in its place.
        </p>
      )}

      <Callout>
        The script passes the same validator a text message does, plus two rules
        only calls have: it must say it is automated, and it must offer a way
        out. Coercive language is refused in Hindi as well as English — a
        message threatening <span className="font-mono">kanooni karyavahi</span>{" "}
        is exactly as much of a problem as one threatening legal action.
        <br />
        <br />
        The figures above were substituted by Python from this case; the
        template contained no digits at all, because a draft containing one is
        rejected. The recording is this same script with those same figures
        spelled as words — &ldquo;one lakh thirty one thousand rupees&rdquo;
        rather than a reader working through the punctuation of
        &ldquo;1,31,000.00&rdquo;.
      </Callout>
    </div>
  );
}

function LedgerRow({ event }: { event: EventRow }) {
  return (
    <div className="flex gap-3 py-1 border-b border-[var(--line)] last:border-0">
      <span className="text-[var(--ink-4)] w-10 shrink-0">#{event.event_id}</span>
      <span className="text-[var(--ink-4)] w-24 shrink-0">{event.actor}</span>
      <span className="text-[var(--ink-2)] w-32 shrink-0">{event.action}</span>
      <span className="text-[var(--ink-3)] w-40 shrink-0 truncate">
        {event.reason_code}
      </span>
      <span
        className="text-[var(--ink-4)] truncate"
        title={`sha256 ${event.this_hash}`}
      >
        {event.this_hash.slice(0, 16)}…
      </span>
    </div>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-4">
      <dt className="text-[var(--ink-3)]">{label}</dt>
      <dd className="font-mono text-[var(--ink)] text-right">{value}</dd>
    </div>
  );
}
