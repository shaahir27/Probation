/**
 * TypeScript data models matching CONTRACT.md Section 9 & ENGINE_SPEC.md.
 */

export type AutonomyLevel = 0 | 1 | 2 | 3;

export type GateDecision =
  | "SHADOW"
  | "SUGGEST"
  | "ASK"
  | "HOLD_THEN_EXECUTE"
  | "EXECUTE_UNDO"
  | "EXECUTE_SILENT";

/**
 * Lifecycle states the D6 API contract freezes for actions. `UNKNOWN` is a real
 * state (an effect that could not be confirmed) and renders as
 * "Result not confirmed" — see `actionStatusLabel`.
 */
export type ActionStatus =
  | "PENDING"
  | "HELD"
  | "DONE"
  | "UNDONE"
  | "CANCELLED"
  | "FAILED"
  | "UNKNOWN";

export interface Citation {
  title: string;
  url: string;
}

/**
 * The server-validated D5 verification card. `fee_status` stays `unknown` until a
 * cited page says otherwise; the UI never renders `unknown` as free.
 */
export interface VerificationCard {
  version: string;
  availability: "validated" | "partial" | "not_checked" | "unavailable";
  fee_status: "payment_mentioned" | "explicit_free" | "unknown";
  fields: Record<string, string | boolean | string[] | null>;
  citations: Citation[];
  reasons: string[];
  fetched_at: string | null;
  ttl_until: string | null;
  extraction_id: string | null;
  provenance?: Record<string, string | number | boolean | null> | null;
}

export interface ItemDetail {
  proposal_id: string;
  review_version: string;
  supported_actions: string[];
  readiness: {
    reply_draft_available: boolean;
    reply_needs_user_input: boolean;
    forward_requires_controlled_recipient: boolean;
  };
  action: string;
  gate: string;
  class_key: string;
  family: string;
  proposed_at: string;
  summary: string;
  occurred_at: string;
  sender_key: string | null;
  explanation: {
    top_clues: string[];
    similar_cases: Array<{ situation_id: string; similarity: number; action_taken: string; summary: string }>;
    summary_reason: string;
  };
  verification_card: VerificationCard | null;
  verification_as_of: string | null;
  web_status: Record<string, unknown>;
  draft: { body_text: string; needs_user_input: boolean; model_id: string | null } | null;
  evidence: Record<string, unknown>;
  licence: Record<string, unknown>;
  user_response: { response: string; edited_action: string | null; responded_at: string } | null;
}

/** POST /queue/{id}/review: the exact payload the owner is about to approve. */
export interface ReviewReceipt {
  version: "v2";
  proposal_id: string;
  reviewed_payload: Record<string, unknown>;
  reviewed_payload_hash: string;
}

/** POST /queue/{id}/respond answers 202: accepted for processing, never complete. */
export interface RespondReceipt {
  ok: true;
  response: string;
  request_id: string;
  id: string;
  status: "recorded";
  status_url: string;
}

export interface ResponseStatus {
  request_id: string;
  proposal_id: string;
  response: string;
  decision_status: string;
  execution_status: string;
  action_id: string | null;
}

export interface QueueItem {
  id: string;
  situation_id: string;
  family: string;
  class_key: string;
  action: string;
  probs: Record<string, number>;
  p_max: number | null;
  novelty: number | null;
  licence_level: number;
  cap: number;
  gate: GateDecision;
  reasons: string[];
  params: Record<string, unknown>;
  explanation: {
    top_clues?: string[];
    similar_cases?: Array<{
      situation_id: string;
      similarity: number;
      action_taken: string;
      summary: string;
    }>;
    summary_reason?: string;
  };
  web: {
    status?: string;
    cap?: number | null;
    source_ids?: string[];
  };
  audit_holdout: boolean;
  proposed_at: string;
  sender_key?: string;
  occurred_at: string;
  summary: string;
  draft?: {
    body_text: string;
    needs_user_input: boolean;
  } | null;
  risk_level?: "low" | "medium" | "high";
  pack_type?: "mail" | "calendar" | "file" | "doc" | "other";
  metadata_table?: Record<string, string>;
  requested_time_ago?: string;
  action_headline?: string;
}

export interface QueueDigest {
  class_key: string;
  action: string;
  family: string;
  count: number;
  ask_count: number;
  suggest_count: number;
  items: string[];
}

export interface QueueGroup {
  class_key: string;
  action: string;
  family: string;
  count: number;
  last_at: string;
}

export interface QueueResponse {
  items: QueueItem[];
  digests: QueueDigest[];
  total_count: number;
  handled_count: number;
  handled_digests: QueueGroup[];
  expired_count: number;
  expired_digests: QueueGroup[];
}

export interface ActionItem {
  id: string;
  proposal_id: string;
  pack: string;
  type: string;
  params: Record<string, unknown>;
  level_required: number;
  recallable: boolean;
  status: ActionStatus;
  hold_until: string | null;
  undo: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
  executed_at: string | null;
  class_key?: string | null;
  family?: string | null;
  summary?: string | null;
  execution_status?: string | null;
  undo_available?: boolean;
  undo_deadline?: string | null;
}

export interface LicenceChangeHistory {
  seq: number;
  created_at: string;
  old_level?: number;
  new_level?: number;
  reason?: string;
}

export interface LicenceItem {
  class_key: string;
  action: string;
  level: AutonomyLevel;
  lower_bound: number;
  n_strong: number;
  k_strong: number;
  n_all: number;
  k_all: number;
  n_recent: number;
  exam_run_id: string | null;
  valid_until: string;
  as_of?: string;
  history_scope?: string;
  reasons: string[];
  checklist?: {
    evidence: { have: number; need: number; met: boolean };
    history?: { have: number; need: number; met: boolean; lower_bound: number };
    recent: { have: number; need: number; met: boolean };
    exam: { met: boolean; run_id: string | null };
    alarm: { met: boolean; last_alarm_at: string | null };
    next: {
      level: number;
      clean_agreements_needed: number;
      remaining_clean: number;
      estimated_days: number;
      basis?: "all" | "strong";
      exam_required?: boolean;
    } | null;
  };
  drift?: {
    cusum: number;
    baseline_err: number;
    last_alarm_at: string | null;
    scope?: string;
  } | null;
  history: LicenceChangeHistory[];
  title?: string;
  action_label?: string;
  pack_icon?: "mail" | "calendar" | "receipt" | "message" | "file" | "users" | "check" | "tag" | "database";
  status_category?: "allowed" | "limited" | "restricted";
  description?: string;
  scope_description?: string;
  human_review_description?: string;
  data_access_description?: string;
  daily_cap?: number;
  current_usage?: number;
  blocked_description?: string;
  evidence_count?: number;
  evidence_samples?: Array<{ date: string; summary: string }>;
  exam_summary?: {
    tested_at?: string;
    level_tested?: string;
    pass_rate?: string;
    flip_rate?: string;
    critical_violations?: number;
  };
  needs_attention?: boolean;
}

export interface TaskReportItem {
  class_key: string;
  action: string;
  family?: string;
  total_evaluated: number;
  same: number;
  different: number;
  would_ask: number;
  censored: number;
  accuracy: number | null;
  needs_attention: boolean;
  lagging?: boolean;
  status: "stable" | "needs_attention" | "not_enough_history";
  title?: string;
  action_label?: string;
}

export interface ReportCardResponse {
  family: string;
  as_of?: string | null;
  total_proposals: number;
  total_evaluated: number;
  same: number;
  different: number;
  would_ask: number;
  censored: number;
  accuracy: number | null;
  scope: string;
  tasks?: TaskReportItem[];
}

export interface MetricWeek {
  week: string;
  asks: number;
  suggestions: number;
  intended_actions: number;
  total: number;
}

/** A measured rate with its denominator; an empty denominator is unavailable, not zero. */
export interface MetricRate {
  numerator: number;
  denominator: number;
  rate: number | null;
}

export interface AlarmRecord {
  seq: number;
  kind: string;
  ref_id: string;
  payload: Record<string, unknown>;
  created_at: string;
}

export interface MetricsSummaryResponse {
  proposals_total: number;
  asks: number;
  suggestions: number;
  /** Proposals the engine wanted to act on. Never an effect that happened. */
  intended_actions: number;
  confirmed_effects: number;
  unconfirmed_effects: number;
  agreement: MetricRate;
  weekly_series: MetricWeek[];
  alarms: AlarmRecord[];
  scope: MetricsScope;
}

export interface MetricsScope {
  family: string | null;
  class_key: string | null;
  action: string | null;
  as_of?: string;
  sources: number;
  evaluated_pairs?: number;
}

export interface HabitItem {
  id: string;
  family: string;
  clue: string;
  clue_value: string;
  action: string;
  k: number;
  n: number;
  lift: number;
  q_value: number;
  statement: string;
  examples: Array<Record<string, unknown>>;
  status: "active" | "denied";
  denied: boolean;
  created_at: string;
}

export interface ChainItem {
  id: string;
  trigger_class_key: string;
  follow_action: string;
  k: number;
  n: number;
  base_rate: number;
  lift: number;
  status: string;
  created_at: string;
}

export interface ExamCase {
  id: string;
  situation_id: string;
  operator: string;
  expectation: string;
  edit_valid: boolean;
  decision_before: string;
  decision_after: string | null;
  violated: boolean;
  critical: boolean;
}

export interface ExamRunItem {
  id: string;
  class_key: string;
  action: string;
  level_tested: number;
  started_at: string;
  finished_at: string | null;
  n_cases: number;
  invariance_flip_rate: number | null;
  critical_violations: number | null;
  passed: boolean | null;
  details: Record<string, unknown>;
  cases: ExamCase[];
}

export interface ExposureBreakdown {
  call_kind: string;
  model_id: string;
  calls: number;
  tokens_in: number;
  tokens_out: number;
  cost_usd: number;
}

export interface ExposureResponse {
  calls: number;
  total_cost_usd: number;
  breakdown: ExposureBreakdown[];
  budget: BudgetSummary;
}

/** Durable spend audit: a hold that may already have been charged is never shown as free. */
export type BudgetSummary =
  | { available: false; reason: string }
  | {
      available: true;
      confirmed_usd: number;
      estimated_usd: number;
      unresolved_holds: number;
      holds_by_state: Record<string, { attempts: number; usd_estimate: number }>;
      never_dispatched: number;
      unit: "usd";
    };

export interface WebFactsCall {
  id: string;
  endpoint: string;
  query: string;
  credits: number;
  ok: boolean;
  latency_ms: number | null;
  created_at: string;
}

export interface WebFactsEntity {
  domain: string;
  status: string;
  facts: Record<string, unknown>;
  sources: Array<{ title?: string; url: string }>;
  fetched_at: string;
}

export interface WebFactsResponse {
  total_calls: number;
  total_credits: number;
  queries: WebFactsCall[];
  entities: WebFactsEntity[];
}

export interface LedgerVerifyResponse {
  ok: boolean;
  seq: number | null;
  length: number;
  head_hash: string;
}

export interface SettingsResponse {
  clock_mode: string;
  budget_hard_limit_usd: number;
  audit_fraction: number;
  l1_min_n: number;
  l1_min_lb: number;
  l2_min_n: number;
  l2_min_lb: number;
  l3_min_n: number;
  l3_min_lb: number;
  cusum_threshold: number;
  psi_threshold: number;
  exam_valid_days: number;
  exam_max_per_day: number;
  user_tz: string;
}

export interface ReplayStateResponse {
  running: boolean;
  speed: number;
  simulated_date: string | null;
  mode: string;
  available: boolean;
  last_request_id?: string | null;
}

export interface BoardEntry {
  id: string;
  pack: string;
  entity: string;
  status: string;
  sources: Array<{ title: string | null; url: string }>;
  item_id?: string | null;
  updated_at: string;
}

export interface BoardResponse {
  pack: string;
  active: boolean;
  entries: BoardEntry[];
  note?: string | null;
}
export interface AdminCommand {
  id: string;
  kind: "deny_habit" | "run_exam";
  status: "PENDING" | "SUCCEEDED" | "FAILED";
  requested_at: string;
  updated_at: string;
  result: Record<string, unknown> | null;
}

export interface DemoAnalyzeResponse {
  model: string;
  tokens_in: number;
  tokens_out: number;
  latency_ms: number;
  usd: number;
  result: Record<string, unknown>;
  redaction_counts: Record<string, number>;
  cached: boolean;
}
