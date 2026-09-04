/**
 * Typed client for the RecoverOS API.
 *
 * The base URL is read from NEXT_PUBLIC_API_BASE so the same build works
 * against a local backend and against the deployed one on Vercel.
 */

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000/api";

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`${res.status} ${res.statusText} on ${path}`);
  }
  return res.json() as Promise<T>;
}

async function post<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { method: "POST" });
  if (!res.ok) {
    throw new Error(`${res.status} ${res.statusText} on ${path}`);
  }
  return res.json() as Promise<T>;
}

/* ------------------------------------------------------------------ types */

export interface ExperimentResult {
  treatment_n: number;
  treatment_recovered: number;
  treatment_rate: number;
  control_n: number;
  control_recovered: number;
  control_rate: number;
  net_lift: number;
  ci_lower: number;
  ci_upper: number;
  is_significant: boolean;
  required_n_per_arm: number | null;
  amount_at_risk_paise: number;
  gross_recovered_paise: number;
  treatment_gross_recovered_paise: number;
  value_weighted_lift: number;
  value_incremental_paise: number;
  breakeven_lift: number;
  incremental_recovered_paise: number;
  incremental_ci_lower_paise: number;
  incremental_ci_upper_paise: number;
  intervention_cost_paise: number;
  roi: number;
  roi_basis: string;
  cost_per_incremental_recovery_paise: number | null;
  guardrails?: GuardrailReport;
}

export interface ClassRow {
  recovery_class: string;
  treatment_n: number;
  treatment_rate: number;
  control_n: number;
  control_rate: number;
  net_lift: number;
  ci_lower: number;
  ci_upper: number;
  is_significant: boolean;
  spend_paise: number;
  at_risk_paise: number;
}

export interface GateRow {
  gate: string;
  name: string;
  blocks: number;
  cases_affected: number;
  spend_avoided_paise: number;
  compliance_avoided_paise: number;
  reasons: Record<string, number>;
}

export interface GuardrailReport {
  gates: GateRow[];
  total_blocks: number;
  total_spend_avoided_paise: number;
  total_compliance_avoided_paise: number;
}

export interface IssuerHealth {
  issuer: string;
  degraded: boolean;
  spike_windows: number;
  peak_failures_in_window: number;
  baseline_mean: number;
  baseline_stdev: number;
  degraded_until: string | null;
}

export interface ExceptionRow {
  reason: string;
  count: number;
  amount_paise: number;
  by_class: Record<string, number>;
}

export interface CaseRow {
  case_id: string;
  entity_type: string;
  entity_id: string;
  customer_id: string;
  amount_at_risk_paise: number;
  recovery_class: string | null;
  rule_id: string | null;
  state: string;
  arm: string;
  touches_used: number;
  resolution: string | null;
  recovered_paise: number;
  intervention_cost_paise: number;
  exception_reason: string | null;
  promise_date: string | null;
}

export interface GateDecision {
  gate_id: string;
  name: string;
  allowed: boolean;
  reason_code: string;
  detail: string;
}

export interface ActionRow {
  action_id: string;
  case_id: string;
  tier: number;
  channel: string;
  status: "SENT" | "BLOCKED";
  blocked_by: string | null;
  gate_decisions_json: GateDecision[] | null;
  message_body: string | null;
  llm_used: boolean;
  llm_rejected_reason: string | null;
  cost_paise: number;
  sent_at: string | null;
  tick: number | null;
  payment_link_url: string | null;
  payment_link_is_real: boolean;
}

export interface EventRow {
  event_id: number;
  ts: string;
  tick: number | null;
  actor: string;
  action: string;
  decision: string;
  reason_code: string;
  payload_json: Record<string, unknown>;
  prev_hash: string;
  this_hash: string;
}

export interface PaymentRow {
  payment_id: string;
  attempt_no: number;
  method: string;
  issuer: string;
  amount_paise: number;
  created_at: string;
  error_code: string;
  error_source: string;
  error_step: string;
  error_reason: string;
  error_description: string;
}

export interface CaseDetail {
  case: CaseRow;
  entity: Record<string, unknown> | null;
  customer: Record<string, unknown> | null;
  payments: PaymentRow[];
  actions: ActionRow[];
  events: EventRow[];
}

export interface AuditStatus {
  valid: boolean;
  records: number;
  broken_at: number[];
  broken_count: number;
  first_break: number | null;
}

export interface DeliveryReport {
  by_tier: {
    tier: number;
    sent: number;
    spend_paise: number;
    channels: Record<string, number>;
  }[];
  messages_from_llm: number;
  messages_from_fallback: number;
  fallback_reasons: Record<string, number>;
  real_payment_links: number;
}

export interface TimelineRow {
  tick: number;
  at: string;
  ist_hour: number;
  day: number;
  quiet: boolean;
  sent: number;
  blocked: number;
  spend_paise: number;
  cum_spend_paise: number;
  recovered_treatment: number;
  recovered_control: number;
  cum_treatment: number;
  cum_control: number;
  cum_treatment_paise: number;
  cum_control_paise: number;
  by_gate: Record<string, number>;
  by_tier: Record<string, number>;
}

export interface Outage {
  issuer: string;
  start_tick: number;
  end_tick: number;
  peak_failures: number;
}

export interface Timeline {
  ticks: number;
  tick_hours: number;
  batch_start: string;
  arm_totals: { treatment: number; control: number };
  outages: Outage[];
  rows: TimelineRow[];
}

export interface FlowClass {
  recovery_class: string;
  at_risk_paise: number;
  recovered_paise: number;
  spend_paise: number;
  cases: number;
  recovered_cases: number;
}

export interface Flow {
  at_risk_paise: number;
  recovered_paise: number;
  spend_paise: number;
  by_class: FlowClass[];
  by_arm: Record<
    string,
    {
      at_risk_paise: number;
      recovered_paise: number;
      cases: number;
      recovered_cases: number;
    }
  >;
}

export interface LlmSample {
  id: string;
  label: string;
  note: string;
  expect: "pass" | "reject";
  channel: string;
  language: string;
  body: string;
}

export interface ValidationResponse {
  ok: boolean;
  reason: string | null;
  checks: Record<string, boolean | number>;
  would_send: string;
  values_from_case: string | null;
  used: "llm_template" | "deterministic_fallback";
  fallback_template: string;
}

export interface SensitivityPoint {
  factor: number;
  net_lift: number;
  ci_lower: number;
  ci_upper: number;
  is_significant: boolean;
}

export interface SensitivityParameter {
  label: string;
  kind: string;
  key: string | null;
  points: SensitivityPoint[];
  low_lift: number;
  high_lift: number;
  swing_pp: number;
  impact: "material" | "moderate" | "negligible";
  breaks_at: number | null;
  breaking_point?: number | null;
}

export interface SensitivityReport {
  committed: {
    treatment_rate: number;
    control_rate: number;
    net_lift: number;
    ci_lower: number;
    ci_upper: number;
    is_significant: boolean;
  };
  sweep_factors: number[];
  parameters: SensitivityParameter[];
  material_count: number;
  breakers: {
    label: string;
    breaks_at: number;
    breaking_point: number | null;
    wrong_by_pct: number | null;
  }[];
  conclusion_holds: boolean;
}

export interface QueueRow {
  case_id: string;
  entity_type: string;
  entity_id: string;
  customer_id: string;
  amount_at_risk_paise: number;
  rule_id: string | null;
  state: string;
  touches_used: number;
  spend_paise: number;
  exception_reason: string | null;
  below_break_even: boolean;
}

export interface QueueEconomics {
  cases: number;
  control_cases: number;
  amount_at_risk_paise: number;
  spend_paise: number;
  share_of_total_spend: number;
  cost_per_review_paise: number;
  assumed_marginal_lift: number;
  expected_incremental_paise: number;
  measured_lift: number;
  ci_lower: number;
  ci_upper: number;
  is_significant: boolean;
  required_n_per_arm: number | null;
  break_even_paise: number | null;
  below_break_even: number;
  below_break_even_paise: number;
  reading: string;
}

export interface QueueAction {
  action: string;
  describes: string;
  closes_case: boolean;
}

export interface QueueResponse {
  queue: QueueRow[];
  economics: QueueEconomics;
  actions: QueueAction[];
}

export interface OperatorActionResult {
  case_id: string;
  action: string;
  operator: string;
  reason: string;
  state: string;
  resolution: string | null;
  recorded_at: string;
  ledger_hash: string;
  executed: boolean;
  note: string;
}

export interface IngestPlan {
  cases: number;
  amount_at_risk_paise: number;
  would_contact: number;
  would_not_contact: number;
  no_action_possible: number;
  planned_spend_paise: number;
  by_class: { recovery_class: string; cases: number }[];
  by_rule: { rule_id: string; cases: number }[];
  by_channel: { channel: string; messages: number }[];
  refusals: {
    gate: string;
    blocks: number;
    amount_paise: number;
    reasons: Record<string, number>;
  }[];
  projection: {
    at_our_assumptions_paise: number;
    low_paise: number;
    high_paise: number;
    band: [number, number];
    basis: string;
  };
  policy: string;
  evaluated_at_ist_hour: number;
  assumptions: string[];
}

export interface IngestResult {
  filename: string;
  rows_read: number;
  rows_usable: number;
  rows_rejected: number;
  amount_unit: string;
  mapping: Record<string, string>;
  unmapped_headers: string[];
  problems: { line: number; column: string | null; problem: string }[];
  plan: IngestPlan;
  /** Always false. The upload is parsed in memory and dropped. */
  stored: boolean;
}

export interface PolicyConfig {
  quiet_start_ist: number;
  quiet_end_ist: number;
  voice_start_ist: number;
  voice_end_ist: number;
  max_touches_per_case: number;
  max_touches_24h: number;
  max_touches_7d: number;
  cooldown_hours: number;
  max_cost_ratio: number;
  min_viable_amount_paise: number;
  compliance_risk_paise: number;
  voice_min_amount_paise: number;
  tier_cost_rupees: Record<string, number>;
  label: string;
}

export interface PolicyBook {
  /** null when no config file is present, which is a supported way to run. */
  source: string | null;
  defaults: PolicyConfig;
  merchants: Record<string, PolicyConfig>;
}

export interface HealthStatus {
  status: string;
  simulation: {
    batch_start: string;
    batch_end: string;
    ticks: number;
    tick_hours: number;
  };
  catalog: { recovery_classes: string[]; gates: string[] };
  data: { cases: number; actions: number; events: number };
  integrations: {
    razorpay_test_mode: boolean;
    llm: boolean;
    voice_tts: boolean;
  };
}

/* ------------------------------------------------------------- endpoints */

export const fetchHealth = () => get<HealthStatus>("/health");
export const fetchPolicy = () => get<PolicyBook>("/policy");
export const fetchSummary = () => get<ExperimentResult>("/metrics/summary");
export const fetchGuardrails = () => get<GuardrailReport>("/metrics/guardrails");
export const fetchDelivery = () => get<DeliveryReport>("/metrics/delivery");
export const fetchIssuerHealth = () =>
  get<{ at: string; issuers: IssuerHealth[] }>("/metrics/issuer-health");
export const fetchExceptions = () =>
  get<{ exceptions: ExceptionRow[] }>("/metrics/exceptions");
export const fetchTimeline = () => get<Timeline>("/metrics/timeline");
export const fetchFlow = () => get<Flow>("/metrics/flow");
export const fetchSensitivity = () =>
  get<SensitivityReport>("/metrics/sensitivity");

export const fetchQueue = () => get<QueueResponse>("/queue");

export async function postQueueAction(
  caseId: string,
  action: string,
  operator: string,
  reason: string,
): Promise<OperatorActionResult> {
  const res = await fetch(`${API_BASE}/queue/${caseId}/act`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action, operator, reason }),
  });
  const body = await res.json();
  if (!res.ok) {
    // The 422 carries the actionable message: a missing field, an
    // already-closed case, or the control-arm guard.
    throw new Error(body.detail ?? `${res.status} ${res.statusText}`);
  }
  return body as OperatorActionResult;
}
export const fetchExperiment = () =>
  get<{ overall: ExperimentResult; per_class: ClassRow[] }>("/metrics/experiment");
export const fetchFunnel = (arm = "treatment") =>
  get<{
    arm: string;
    total: number;
    by_state: Record<string, number>;
    by_class: Record<string, number>;
    by_touches: Record<string, number>;
  }>(`/metrics/funnel?arm=${arm}`);

export const fetchCases = (params: Record<string, string | number> = {}) => {
  const qs = new URLSearchParams(
    Object.entries(params).map(([k, v]) => [k, String(v)]),
  ).toString();
  return get<{ total: number; cases: CaseRow[] }>(`/cases${qs ? `?${qs}` : ""}`);
};
export const fetchCase = (id: string) => get<CaseDetail>(`/cases/${id}`);

export const fetchLlmSamples = () =>
  get<{
    samples: LlmSample[];
    banned_phrases: string[];
    length_caps: Record<string, number>;
    llm_calls_this_process: number;
  }>("/llm/samples");

export async function validateDraft(draft: {
  body: string;
  channel: string;
  language: string;
}): Promise<ValidationResponse> {
  const res = await fetch(`${API_BASE}/llm/validate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(draft),
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText} on /llm/validate`);
  return res.json() as Promise<ValidationResponse>;
}

export const verifyLedger = () => get<AuditStatus>("/audit/verify");
export const tamperLedger = () =>
  post<{ event_id: number; before: unknown; after: unknown }>("/audit/tamper");
export const restoreLedger = () =>
  post<{ status: string; restored: number[]; chain: AuditStatus }>(
    "/audit/restore",
  );
export const runBatch = () => post<Record<string, unknown>>("/batch/run");

/* -------------------------------------------------------------- SSE feed */

export type BatchEvent =
  | { type: "prepared"; cases: number }
  | { type: "detector"; degraded: string[]; report: IssuerHealth[] }
  | {
      type: "tick";
      tick: number;
      at: string;
      ist_hour: number;
      actions: number;
      sent: number;
      blocked: number;
      recovered: number;
    }
  | { type: "sent"; case: string; tier: number; channel: string }
  | { type: "blocked"; case: string; gate: string; reason: string }
  | { type: "recovered"; case: string; amount_paise: number }
  | { type: "done"; summary: Record<string, unknown> }
  | { type: "error"; message: string };

/**
 * Open the batch stream. Returns the EventSource so the caller can close it —
 * an SSE connection left open after the component unmounts keeps the batch
 * running against a browser that is no longer listening.
 */
export function streamBatch(onEvent: (e: BatchEvent) => void): EventSource {
  const source = new EventSource(`${API_BASE}/batch/stream`);
  source.onmessage = (msg) => {
    try {
      onEvent(JSON.parse(msg.data) as BatchEvent);
    } catch {
      /* a malformed frame should not tear down the stream */
    }
  };
  source.onerror = () => source.close();
  return source;
}
