/**
 * Hand-written runtime decoders for every API payload the UI renders.
 *
 * A TypeScript assertion validates nothing: every value crossing the network
 * boundary is decoded here or it is not shown. A decode failure is an
 * `invalid_response` error, which renders as an unavailable panel — never as
 * fixture data, never as a success.
 */

import {
  ActionItem,
  AdminCommand,
  BoardEntry,
  BoardResponse,
  ChainItem,
  Citation,
  DemoAnalyzeResponse,
  ExamRunItem,
  ExposureResponse,
  HabitItem,
  ItemDetail,
  LedgerVerifyResponse,
  LicenceItem,
  MetricsSummaryResponse,
  QueueItem,
  QueueResponse,
  ReplayStateResponse,
  ReportCardResponse,
  ReviewReceipt,
  RespondReceipt,
  ResponseStatus,
  SettingsResponse,
  VerificationCard,
  WebFactsResponse,

  MetricWeek,
  BudgetSummary,} from "./types";

export class ApiError extends Error {
  constructor(readonly code: string, message: string, readonly status?: number) {
    super(message);
    this.name = "ApiError";
  }
}

/** Every decoder refuses a payload it cannot fully explain. */
export function unreadable(label: string, detail = ""): never {
  throw new ApiError(
    "invalid_response",
    `Probation returned an unreadable ${label}${detail ? ` (${detail})` : ""}.`,
  );
}

export function recordValue(value: unknown, label: string): Record<string, unknown> {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    return unreadable(label);
  }
  return value as Record<string, unknown>;
}

export function stringValue(value: unknown, label: string): string {
  if (typeof value !== "string") return unreadable(label);
  return value;
}

/** A filter that was not applied reads as null; an absent key is not the same as "". */
export function nullableStringValue(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

export function optionalStringValue(value: unknown, label: string): string | null {
  if (value === null || value === undefined) return null;
  if (typeof value !== "string") return unreadable(label);
  return value;
}

export function booleanValue(value: unknown, label: string): boolean {
  if (typeof value !== "boolean") return unreadable(label);
  return value;
}

export function finiteNumberValue(value: unknown, label: string): number {
  if (typeof value !== "number" || !Number.isFinite(value)) return unreadable(label);
  return value;
}

export function countValue(value: unknown, label: string): number {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < 0) {
    return unreadable(`${label} count`);
  }
  return value;
}

export function arrayValue(value: unknown, label: string): unknown[] {
  if (!Array.isArray(value)) return unreadable(label);
  return value;
}

export function stringArrayValue(value: unknown, label: string): string[] {
  return arrayValue(value, label).map((entry) => stringValue(entry, label));
}

function optionalStringArrayValue(value: unknown, label: string): string[] {
  if (value === undefined || value === null) return [];
  return stringArrayValue(value, label);
}

function optionalNumberValue(value: unknown, label: string): number | null {
  if (value === undefined || value === null) return null;
  return finiteNumberValue(value, label);
}

function optionalRecordValue(value: unknown, label: string): Record<string, unknown> {
  if (value === undefined || value === null) return {};
  return recordValue(value, label);
}

function stringKeyedNumbers(value: unknown, label: string): Record<string, number> {
  const source = optionalRecordValue(value, label);
  const output: Record<string, number> = {};
  Object.entries(source).forEach(([key, entry]) => {
    output[key] = finiteNumberValue(entry, `${label} ${key}`);
  });
  return output;
}

const GATES = new Set([
  "SHADOW",
  "SUGGEST",
  "ASK",
  "HOLD_THEN_EXECUTE",
  "EXECUTE_UNDO",
  "EXECUTE_SILENT",
]);

export function decodeGate(value: unknown, label: string): QueueItem["gate"] {
  const gate = stringValue(value, `${label} gate`);
  if (!GATES.has(gate)) return unreadable(`${label} gate`);
  return gate as QueueItem["gate"];
}

export function decodeQueueItem(value: unknown): QueueItem {
  const row = recordValue(value, "email");
  if (typeof row.id !== "string" || typeof row.action !== "string") {
    return unreadable("email", "missing identity");
  }
  if (typeof row.gate !== "string") return unreadable("email gate");
  if (!GATES.has(row.gate)) return unreadable("email gate");
  const explanation = optionalRecordValue(row.explanation, "email explanation");
  const draftRow = row.draft === null || row.draft === undefined ? null : recordValue(row.draft, "email draft");
  return {
    id: row.id,
    situation_id: optionalStringValue(row.situation_id, "email situation") ?? "",
    family: optionalStringValue(row.family, "email family") ?? "",
    class_key: optionalStringValue(row.class_key, "email task") ?? "",
    action: row.action,
    gate: row.gate as QueueItem["gate"],
    reasons: optionalStringArrayValue(row.reasons, "email reasons"),
    params: optionalRecordValue(row.params, "email parameters"),
    probs: stringKeyedNumbers(row.probs, "email probability"),
    p_max: optionalNumberValue(row.p_max, "email confidence"),
    novelty: optionalNumberValue(row.novelty, "email novelty"),
    licence_level: optionalNumberValue(row.licence_level, "email permission level") ?? 0,
    cap: optionalNumberValue(row.cap, "email cap") ?? 0,
    audit_holdout: row.audit_holdout === undefined ? false : booleanValue(row.audit_holdout, "email spot check"),
    proposed_at: optionalStringValue(row.proposed_at, "email proposed time") ?? "",
    occurred_at: optionalStringValue(row.occurred_at, "email occurred time") ?? "",
    sender_key: optionalStringValue(row.sender_key, "email sender") ?? undefined,
    summary: typeof row.summary === "string" ? row.summary : "",
    web: optionalRecordValue(row.web, "email web status") as QueueItem["web"],
    explanation: explanation as QueueItem["explanation"],
    draft: draftRow
      ? {
          body_text: optionalStringValue(draftRow.body_text, "email draft body") ?? "",
          needs_user_input:
            draftRow.needs_user_input === undefined ? false : booleanValue(draftRow.needs_user_input, "email draft state"),
        }
      : null,
  };
}

function decodeQueueGroups(value: unknown, label: string): QueueResponse["handled_digests"] {
  return arrayValue(value ?? [], label).map((entry) => {
    const row = recordValue(entry, label);
    return {
      class_key: stringValue(row.class_key, `${label} task`),
      action: stringValue(row.action, `${label} action`),
      family: stringValue(row.family, `${label} family`),
      count: countValue(row.count, `${label} count`),
      last_at: stringValue(row.last_at, `${label} time`),
    };
  });
}

export function decodeQueueResponse(value: unknown): QueueResponse {
  const payload = recordValue(value, "review list");
  return {
    items: arrayValue(payload.items, "review list").map(decodeQueueItem),
    digests: arrayValue(payload.digests ?? [], "review groups") as QueueResponse["digests"],
    total_count: countValue(payload.total_count, "review list"),
    handled_count: countValue(payload.handled_count ?? 0, "handled list"),
    handled_digests: decodeQueueGroups(payload.handled_digests, "handled groups"),
    expired_count: countValue(payload.expired_count ?? 0, "expired list"),
    expired_digests: decodeQueueGroups(payload.expired_digests, "expired groups"),
  };
}

export function decodeWatchingResponse(value: unknown): { items: QueueItem[]; total_count: number } {
  const payload = recordValue(value, "watching list");
  return {
    items: arrayValue(payload.items, "watching list").map(decodeQueueItem),
    total_count: countValue(payload.total_count, "watching list"),
  };
}

const CITATION_AVAILABILITY = new Set(["validated", "partial", "not_checked", "unavailable"]);
const FEE_STATUS = new Set(["payment_mentioned", "explicit_free", "unknown"]);

export function decodeCitation(value: unknown): Citation {
  const row = recordValue(value, "source citation");
  return {
    title: optionalStringValue(row.title, "citation title") ?? "",
    url: stringValue(row.url, "citation link"),
  };
}

export function decodeVerificationCard(value: unknown): VerificationCard | null {
  if (value === null || value === undefined) return null;
  const row = recordValue(value, "verification card");
  const availability = stringValue(row.availability, "verification availability");
  if (!CITATION_AVAILABILITY.has(availability)) return unreadable("verification availability");
  const fee = row.fee_status === undefined ? "unknown" : stringValue(row.fee_status, "verification fee status");
  if (!FEE_STATUS.has(fee)) return unreadable("verification fee status");
  const fields: VerificationCard["fields"] = {};
  Object.entries(optionalRecordValue(row.fields, "verification fields")).forEach(([key, entry]) => {
    if (entry === null) fields[key] = null;
    else if (typeof entry === "boolean" || typeof entry === "string") fields[key] = entry;
    else if (Array.isArray(entry)) fields[key] = entry.map((item) => stringValue(item, "verification field list"));
    else unreadable("verification field value", key);
  });
  return {
    version: optionalStringValue(row.version, "verification version") ?? "unlabelled",
    availability: availability as VerificationCard["availability"],
    fee_status: fee as VerificationCard["fee_status"],
    fields,
    citations: arrayValue(row.citations ?? [], "verification sources").map(decodeCitation),
    reasons: optionalStringArrayValue(row.reasons, "verification reasons"),
    fetched_at: optionalStringValue(row.fetched_at, "verification checked time"),
    ttl_until: optionalStringValue(row.ttl_until, "verification valid until"),
    extraction_id: optionalStringValue(row.extraction_id, "verification extraction"),
    provenance:
      row.provenance === undefined || row.provenance === null
        ? null
        : (recordValue(row.provenance, "verification provenance") as VerificationCard["provenance"]),
  };
}

export function decodeItemDetail(value: unknown): ItemDetail {
  const row = recordValue(value, "email details");
  const situation = optionalRecordValue(row.situation, "email situation");
  const readiness = optionalRecordValue(row.readiness, "email readiness");
  const draftRow = row.draft === null || row.draft === undefined ? null : recordValue(row.draft, "email draft");
  const userResponse =
    row.user_response === null || row.user_response === undefined
      ? null
      : recordValue(row.user_response, "email answer");
  return {
    proposal_id: stringValue(row.proposal_id, "email identifier"),
    review_version: optionalStringValue(row.review_version, "review version") ?? "",
    supported_actions: optionalStringArrayValue(row.supported_actions, "supported actions"),
    readiness: {
      reply_draft_available: readiness.reply_draft_available === undefined ? false : booleanValue(readiness.reply_draft_available, "reply readiness"),
      reply_needs_user_input: readiness.reply_needs_user_input === undefined ? false : booleanValue(readiness.reply_needs_user_input, "reply input readiness"),
      forward_requires_controlled_recipient:
        readiness.forward_requires_controlled_recipient === undefined
          ? false
          : booleanValue(readiness.forward_requires_controlled_recipient, "forward readiness"),
    },
    action: optionalStringValue(row.action, "email action") ?? "",
    gate: row.gate === undefined ? "" : stringValue(row.gate, "email gate"),
    class_key: optionalStringValue(row.class_key, "email task") ?? "",
    family: optionalStringValue(row.family, "email family") ?? "",
    proposed_at: optionalStringValue(row.proposed_at, "email proposed time") ?? "",
    summary: optionalStringValue(situation.summary, "email summary") ?? "",
    occurred_at: optionalStringValue(situation.occurred_at, "email occurred time") ?? "",
    sender_key: optionalStringValue(situation.sender_key, "email sender"),
    explanation: {
      top_clues: optionalStringArrayValue(
        optionalRecordValue(row.explanation, "email explanation").top_clues,
        "email clues",
      ),
      similar_cases: arrayValue(
        optionalRecordValue(row.explanation, "email explanation").similar_cases ?? [],
        "similar cases",
      ) as ItemDetail["explanation"]["similar_cases"],
      summary_reason:
        optionalStringValue(
          optionalRecordValue(row.explanation, "email explanation").summary_reason,
          "email reason",
        ) ?? "",
    },
    verification_card: decodeVerificationCard(row.verification_card),
    verification_as_of: optionalStringValue(row.verification_as_of, "verification time"),
    web_status: optionalRecordValue(row.web_status, "web status") as ItemDetail["web_status"],
    draft: draftRow
      ? {
          body_text: optionalStringValue(draftRow.body_text, "email draft body") ?? "",
          needs_user_input: draftRow.needs_user_input === undefined ? false : booleanValue(draftRow.needs_user_input, "email draft state"),
          model_id: optionalStringValue(draftRow.model_id, "draft model"),
        }
      : null,
    evidence: optionalRecordValue(row.evidence, "evidence line") as ItemDetail["evidence"],
    licence: optionalRecordValue(row.licence, "permission") as ItemDetail["licence"],
    user_response: userResponse
      ? {
          response: stringValue(userResponse.response, "recorded answer"),
          edited_action: optionalStringValue(userResponse.edited_action, "recorded edit"),
          responded_at: optionalStringValue(userResponse.responded_at, "answer time") ?? "",
        }
      : null,
  };
}

const ACTION_STATUSES = new Set(["PENDING", "HELD", "DONE", "UNDONE", "CANCELLED", "FAILED", "UNKNOWN"]);

export function decodeActionItem(value: unknown): ActionItem {
  const row = recordValue(value, "action");
  const status = stringValue(row.status, "action status").toUpperCase();
  if (!ACTION_STATUSES.has(status)) return unreadable("action status");
  return {
    id: stringValue(row.id, "action identifier"),
    proposal_id: optionalStringValue(row.proposal_id, "action proposal") ?? "",
    pack: optionalStringValue(row.pack, "action pack") ?? "",
    type: optionalStringValue(row.type, "action type") ?? "",
    params: optionalRecordValue(row.params, "action parameters"),
    level_required: optionalNumberValue(row.level_required, "action level") ?? 0,
    recallable: row.recallable === undefined ? false : booleanValue(row.recallable, "action recall"),
    status: status as ActionItem["status"],
    hold_until: optionalStringValue(row.hold_until, "action hold"),
    undo: row.undo === null || row.undo === undefined ? null : recordValue(row.undo, "action undo"),
    created_at: optionalStringValue(row.created_at, "action created time") ?? "",
    updated_at: optionalStringValue(row.updated_at, "action updated time") ?? "",
    executed_at: optionalStringValue(row.executed_at, "action executed time"),
    class_key: optionalStringValue(row.class_key, "action task"),
    family: optionalStringValue(row.family, "action family"),
    summary: optionalStringValue(row.summary, "action summary"),
    execution_status: optionalStringValue(row.execution_status, "action execution status"),
    undo_available: row.undo_available === undefined ? false : booleanValue(row.undo_available, "undo availability"),
    undo_deadline: optionalStringValue(row.undo_deadline, "undo deadline"),
  };
}

export function decodeActionsResponse(value: unknown): { actions: ActionItem[]; total_count: number } {
  const payload = recordValue(value, "actions");
  return {
    actions: arrayValue(payload.actions, "actions").map(decodeActionItem),
    total_count: countValue(payload.total_count, "actions"),
  };
}

export function decodeLicenceList(value: unknown): { licences: LicenceItem[]; total_count: number } {
  const payload = recordValue(value, "permissions");
  const rows = arrayValue(payload.licences, "permissions").map((entry) => {
    const row = recordValue(entry, "permission");
    return {
      ...row,
      class_key: stringValue(row.class_key, "permission task"),
      action: stringValue(row.action, "permission action"),
      level: finiteNumberValue(row.level, "permission level") as LicenceItem["level"],
      lower_bound: finiteNumberValue(row.lower_bound, "permission estimate"),
      n_strong: countValue(row.n_strong, "permission evidence"),
      k_strong: countValue(row.k_strong, "permission matches"),
      n_all: countValue(row.n_all, "permission history"),
      k_all: countValue(row.k_all, "permission history matches"),
      n_recent: countValue(row.n_recent, "permission recent"),
      reasons: optionalStringArrayValue(row.reasons, "permission reasons"),
      history: arrayValue(row.history ?? [], "permission history") as LicenceItem["history"],
      exam_run_id: optionalStringValue(row.exam_run_id, "permission test"),
      valid_until: optionalStringValue(row.valid_until, "permission validity") ?? "",
    } satisfies LicenceItem;
  });
  return { licences: rows, total_count: countValue(payload.total_count, "permissions") };
}

export function decodeBootstrap(value: unknown) {
  const payload = recordValue(value, "setup");
  if (
    typeof payload.version !== "string" ||
    !["private", "synthetic"].includes(String(payload.profile)) ||
    typeof payload.auth_required !== "boolean"
  ) {
    throw new ApiError("invalid_response", "Probation returned incomplete setup information.");
  }
  return {
    version: payload.version,
    profile: payload.profile as "private" | "synthetic",
    auth_required: payload.auth_required,
    demo_login: payload.demo_login === true,
  };
}

export function decodeReviewReceipt(value: unknown): ReviewReceipt {
  const payload = recordValue(value, "review check");
  if (
    payload.version !== "v2" ||
    typeof payload.proposal_id !== "string" ||
    !/^[a-f0-9]{64}$/.test(String(payload.reviewed_payload_hash)) ||
    !payload.reviewed_payload ||
    typeof payload.reviewed_payload !== "object" ||
    Array.isArray(payload.reviewed_payload)
  ) {
    throw new ApiError(
      "invalid_response",
      "Probation could not confirm what you reviewed. Nothing was submitted.",
    );
  }
  return payload as unknown as ReviewReceipt;
}

export function decodeRespondReceipt(value: unknown): RespondReceipt {
  const payload = recordValue(value, "request status");
  if (
    payload.ok !== true ||
    typeof payload.request_id !== "string" ||
    payload.status !== "recorded" ||
    typeof payload.status_url !== "string"
  ) {
    throw new ApiError("invalid_response", "Probation did not confirm that the request was recorded.");
  }
  return payload as unknown as RespondReceipt;
}

export function decodeResponseStatus(value: unknown): ResponseStatus {
  const payload = recordValue(value, "request status");
  if (
    ["request_id", "proposal_id", "response", "decision_status", "execution_status"].some(
      (key) => typeof payload[key] !== "string",
    ) ||
    (payload.action_id !== null && typeof payload.action_id !== "string")
  ) {
    throw new ApiError("invalid_response", "Probation returned an unreadable request status.");
  }
  return payload as unknown as ResponseStatus;
}

export function decodeReplayState(value: unknown): ReplayStateResponse {
  const row = recordValue(value, "replay state");
  const speed = finiteNumberValue(row.speed, "replay speed");
  if (![1, 10, 100].includes(speed)) return unreadable("replay speed");
  return {
    running: booleanValue(row.running, "replay running"),
    speed,
    simulated_date: optionalStringValue(row.simulated_date, "replay date"),
    mode: optionalStringValue(row.mode, "clock mode") ?? "live",
    available: row.available === undefined ? true : booleanValue(row.available, "replay availability"),
    last_request_id: optionalStringValue(row.last_request_id, "replay request"),
  };
}

export function decodeAdminCommand(value: unknown): AdminCommand {
  const row = recordValue(value, "request");
  const kind = stringValue(row.kind, "request kind");
  const status = stringValue(row.status, "request status");
  if (!["deny_habit", "run_exam"].includes(kind) || !["PENDING", "SUCCEEDED", "FAILED"].includes(status)) {
    return unreadable("request");
  }
  return {
    id: stringValue(row.id, "request identifier"),
    kind: kind as AdminCommand["kind"],
    status: status as AdminCommand["status"],
    requested_at: optionalStringValue(row.requested_at, "request time") ?? "",
    updated_at: optionalStringValue(row.updated_at, "request update time") ?? "",
    result: row.result === null || row.result === undefined ? null : recordValue(row.result, "request result"),
  };
}

export function decodeCommandEnvelope(value: unknown): { ok: boolean; command: AdminCommand } {
  const row = recordValue(value, "request");
  return { ok: booleanValue(row.ok, "request acceptance"), command: decodeAdminCommand(row.command) };
}

export function decodeReportCard(value: unknown): ReportCardResponse {
  const row = recordValue(value, "report card");
  return {
    family: stringValue(row.family, "report family"),
    as_of: optionalStringValue(row.as_of, "report date"),
    total_proposals: countValue(row.total_proposals, "report proposals"),
    total_evaluated: countValue(row.total_evaluated, "report evaluations"),
    same: countValue(row.same, "report matches"),
    different: countValue(row.different, "report differences"),
    would_ask: countValue(row.would_ask, "report asks"),
    censored: countValue(row.censored, "report unresolved"),
    accuracy: optionalNumberValue(row.accuracy, "report agreement"),
    scope: optionalStringValue(row.scope, "report scope") ?? "",
    tasks: arrayValue(row.tasks ?? [], "report tasks") as ReportCardResponse["tasks"],
  };
}

export function decodeMetricsSummary(value: unknown): MetricsSummaryResponse {
  const row = recordValue(value, "metrics");
  const agreement = recordValue(row.agreement ?? {}, "metrics agreement");
  const scope = recordValue(row.scope ?? {}, "metrics scope");
  return {
    proposals_total: countValue(row.proposals_total, "metrics proposals"),
    asks: countValue(row.asks, "metrics asks"),
    suggestions: countValue(row.suggestions, "metrics suggestions"),
    intended_actions: countValue(row.intended_actions, "metrics intended actions"),
    confirmed_effects: countValue(row.confirmed_effects, "metrics confirmed effects"),
    unconfirmed_effects: countValue(row.unconfirmed_effects, "metrics unresolved effects"),
    agreement: {
      numerator: countValue(agreement.numerator, "agreement numerator"),
      denominator: countValue(agreement.denominator, "agreement denominator"),
      rate: optionalNumberValue(agreement.rate, "agreement rate"),
    },
    weekly_series: arrayValue(row.weekly_series ?? [], "metrics weeks").map(decodeMetricWeek),
    alarms: arrayValue(row.alarms ?? [], "metrics alarms") as MetricsSummaryResponse["alarms"],
    scope: {
      family: nullableStringValue(scope.family),
      class_key: nullableStringValue(scope.class_key),
      action: nullableStringValue(scope.action),
      as_of: optionalStringValue(scope.as_of, "metrics cutoff") ?? undefined,
      sources: countValue(scope.sources, "metrics sources"),
      evaluated_pairs: scope.evaluated_pairs === undefined
        ? undefined
        : countValue(scope.evaluated_pairs, "metrics evaluated pairs"),
    },
  };
}

function decodeMetricWeek(value: unknown): MetricWeek {
  const row = recordValue(value, "metrics week");
  return {
    week: optionalStringValue(row.week, "metrics week label") ?? "",
    asks: countValue(row.asks, "week asks"),
    suggestions: countValue(row.suggestions, "week suggestions"),
    intended_actions: countValue(row.intended_actions, "week intended actions"),
    total: countValue(row.total, "week total"),
  };
}

export function decodeHabitList(value: unknown): { habits: HabitItem[] } {
  const row = recordValue(value, "habits");
  return { habits: arrayValue(row.habits, "habits") as HabitItem[] };
}

export function decodeDemoAnalyze(value: unknown): DemoAnalyzeResponse {
  const row = recordValue(value, "live analysis");
  return {
    model: stringValue(row.model, "live analysis model"),
    tokens_in: countValue(row.tokens_in, "live analysis input tokens"),
    tokens_out: countValue(row.tokens_out, "live analysis output tokens"),
    latency_ms: countValue(row.latency_ms, "live analysis latency"),
    usd: finiteNumberValue(row.usd, "live analysis cost"),
    result: recordValue(row.result, "live analysis result"),
    redaction_counts: Object.fromEntries(
      Object.entries(recordValue(row.redaction_counts ?? {}, "live analysis redactions")).map(
        ([key, value]) => [key, countValue(value, "live analysis redaction")],
      ),
    ),
    cached: booleanValue(row.cached, "live analysis cache flag"),
  };
}

export function decodeChainList(value: unknown): { chains: ChainItem[] } {
  const row = recordValue(value, "chains");
  return { chains: arrayValue(row.chains, "chains") as ChainItem[] };
}

export function decodeExamRuns(value: unknown): { runs: ExamRunItem[] } {
  const row = recordValue(value, "tests");
  return { runs: arrayValue(row.runs, "tests") as ExamRunItem[] };
}

export function decodeExposure(value: unknown): ExposureResponse {
  const row = recordValue(value, "usage");
  return {
    calls: countValue(row.calls, "usage calls"),
    total_cost_usd: finiteNumberValue(row.total_cost_usd, "usage cost"),
    breakdown: arrayValue(row.breakdown ?? [], "usage breakdown") as ExposureResponse["breakdown"],
    budget: decodeBudgetSummary(row.budget),
  };
}

function decodeBudgetSummary(value: unknown): BudgetSummary {
  const row = recordValue(value ?? {}, "budget");
  if (row.available !== true) {
    return { available: false, reason: optionalStringValue(row.reason, "budget reason") ?? "unavailable" };
  }
  const holds = recordValue(row.holds_by_state ?? {}, "budget holds");
  const holdsByState: Record<string, { attempts: number; usd_estimate: number }> = {};
  for (const [state, entry] of Object.entries(holds)) {
    const record = recordValue(entry, `budget hold ${state}`);
    holdsByState[state] = {
      attempts: countValue(record.attempts, `budget ${state} attempts`),
      usd_estimate: finiteNumberValue(record.usd_estimate, `budget ${state} estimate`),
    };
  }
  return {
    available: true,
    confirmed_usd: finiteNumberValue(row.confirmed_usd, "budget confirmed"),
    estimated_usd: finiteNumberValue(row.estimated_usd, "budget estimated"),
    unresolved_holds: countValue(row.unresolved_holds, "budget unresolved holds"),
    holds_by_state: holdsByState,
    never_dispatched: countValue(row.never_dispatched, "budget never dispatched"),
    unit: "usd",
  };
}

export function decodeWebFacts(value: unknown): WebFactsResponse {
  const row = recordValue(value, "web record");
  return {
    total_calls: countValue(row.total_calls, "web calls"),
    total_credits: finiteNumberValue(row.total_credits, "web credits"),
    queries: arrayValue(row.queries ?? [], "web queries") as WebFactsResponse["queries"],
    entities: arrayValue(row.entities ?? [], "web entities") as WebFactsResponse["entities"],
  };
}

export function decodeLedgerVerify(value: unknown): LedgerVerifyResponse {
  const row = recordValue(value, "activity record check");
  return {
    ok: booleanValue(row.ok, "record integrity"),
    seq: row.seq === null ? null : countValue(row.seq, "record position"),
    length: countValue(row.length, "record length"),
    head_hash: stringValue(row.head_hash, "record fingerprint"),
  };
}

export function decodeSettings(value: unknown): SettingsResponse {
  const row = recordValue(value, "settings");
  const numbers = [
    "budget_hard_limit_usd", "audit_fraction", "l1_min_n", "l1_min_lb", "l2_min_n", "l2_min_lb",
    "l3_min_n", "l3_min_lb", "cusum_threshold", "psi_threshold", "exam_valid_days", "exam_max_per_day",
  ] as const;
  const output = {
    clock_mode: stringValue(row.clock_mode, "clock mode"),
    user_tz: optionalStringValue(row.user_tz, "time zone") ?? "unavailable",
  } as Record<string, string | number>;
  numbers.forEach((key) => {
    output[key] = finiteNumberValue(row[key], `setting ${key}`);
  });
  return output as unknown as SettingsResponse;
}

export function decodeBoard(value: unknown): BoardResponse {
  const row = recordValue(value, "board");
  return {
    pack: stringValue(row.pack, "board pack"),
    active: booleanValue(row.active, "board activity"),
    entries: arrayValue(row.entries ?? [], "board entries").map((entry) => {
      const item = recordValue(entry, "board entry");
      return {
        id: stringValue(item.id, "entry identifier"),
        pack: optionalStringValue(item.pack, "entry pack") ?? "",
        entity: optionalStringValue(item.entity, "entry entity") ?? "",
        status: optionalStringValue(item.status, "entry status") ?? "",
        sources: arrayValue(item.sources ?? [], "entry sources").map((source) => {
          const row2 = recordValue(source, "entry source");
          return { title: optionalStringValue(row2.title, "source title"), url: stringValue(row2.url, "source link") };
        }),
        item_id: optionalStringValue(item.item_id, "entry item"),
        updated_at: optionalStringValue(item.updated_at, "entry update time") ?? "",
      } satisfies BoardEntry;
    }),
    note: optionalStringValue(row.note, "board note"),
  };
}
