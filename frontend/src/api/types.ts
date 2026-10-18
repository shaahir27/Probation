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

export type ActionStatus =
  | "PENDING"
  | "HELD"
  | "DONE"
  | "UNDONE"
  | "CANCELLED"
  | "FAILED";

export interface QueueItem {
  id: string;
  situation_id: string;
  family: string;
  class_key: string;
  action: string;
  probs: Record<string, number>;
  p_max: number;
  novelty: number;
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
    cap?: number;
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

export interface QueueResponse {
  items: QueueItem[];
  digests: QueueDigest[];
  total_count: number;
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
  class_key?: string;
  family?: string;
  summary?: string;
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
  reasons: string[];
  drift?: {
    cusum: number;
    baseline_err: number;
    last_alarm_at: string | null;
  } | null;
  history: LicenceChangeHistory[];
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
}

export interface MetricWeek {
  week: string;
  asks: number;
  suggestions: number;
  auto_actions: number;
  total: number;
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
  automatic_actions: number;
  agreement_rate: number | null;
  weekly_series: MetricWeek[];
  alarms: AlarmRecord[];
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
}

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
  simulated_date: string;
  mode: string;
}

export interface BoardEntry {
  id: string;
  pack: string;
  entity: string;
  status: string;
  sources: Array<{ title?: string; url: string }>;
  item_id?: string;
  updated_at: string;
}

export interface BoardResponse {
  pack: string;
  active: boolean;
  entries: BoardEntry[];
  note?: string;
}
