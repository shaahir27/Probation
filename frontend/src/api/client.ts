/**
 * The only browser-side network module. The owner key is sent once to exchange for a
 * short-lived HttpOnly session cookie; it is never stored here, in a URL, storage, a
 * query key or a log line. Private requests rely on that cookie plus a same-origin CSRF
 * marker, so refreshing the page keeps the session without exposing the key to script.
 *
 * Every read is cancellable and stamped with the session generation it started in,
 * so a response that arrives after logout can never repopulate state.
 */

import type {
  ActionItem,
  AdminCommand,
  BoardResponse,
  ChainItem,
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
  RespondReceipt,
  ResponseStatus,
  ReviewReceipt,
  SettingsResponse,
  WebFactsResponse,
  DemoAnalyzeResponse,
} from "./types";
import {
  ApiError,
  decodeActionsResponse,
  decodeAdminCommand,
  decodeBoard,
  decodeBootstrap,
  decodeChainList,
  decodeCommandEnvelope,
  decodeDemoAnalyze,
  decodeExamRuns,
  decodeExposure,
  decodeHabitList,
  decodeItemDetail,
  decodeLedgerVerify,
  decodeLicenceList,
  decodeMetricsSummary,
  decodeQueueResponse,
  decodeReplayState,
  decodeReportCard,
  decodeRespondReceipt,
  decodeResponseStatus,
  decodeReviewReceipt,
  decodeSettings,
  decodeWatchingResponse,
  decodeWebFacts,
  recordValue,
} from "./validation";

const API_BASE = "/api";
const CSRF_HEADER = "X-Probation-CSRF";
const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);

export { ApiError };

let sessionGeneration = 0;
const inflight = new Set<AbortController>();

/** Owner signed in: bump the generation so any earlier read is discarded. */
export function beginOwnerSession(): number {
  sessionGeneration += 1;
  return sessionGeneration;
}

/**
 * Owner signed out (or was locked out): bump the generation and abort every in-flight
 * request so a late response cannot repopulate state. The server-side session is
 * destroyed separately by `apiClient.endSession()`.
 */
export function clearOwnerSession(): number {
  sessionGeneration += 1;
  inflight.forEach((controller) => controller.abort());
  inflight.clear();
  return sessionGeneration;
}

export function getSessionGeneration(): number {
  return sessionGeneration;
}

/** A stable pre-created request ID for one mutation attempt, safe to retry as-is. */
export function newRequestId(prefix: string): string {
  const random =
    typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
      ? crypto.randomUUID()
      : `${Date.now().toString(36)}${Math.random().toString(36).slice(2)}`;
  return `${prefix}-${random}`.slice(0, 160);
}

export function isAbortError(error: unknown): boolean {
  return error instanceof DOMException
    ? error.name === "AbortError"
    : error instanceof Error && (error.name === "AbortError" || (error as ApiError).code === "aborted");
}

/** 401/403: the session is not authorised for this read. Never shown as empty data. */
export function isLockedError(error: unknown): boolean {
  if (!(error instanceof ApiError)) return false;
  return error.status === 401 || error.status === 403 || error.code === "unauthorized" || error.code === "forbidden";
}

/** 409 with a decision-relevant code: the owner must review again before resending. */
export const CONFLICT_CODES: readonly string[] = [
  "review_binding_changed",
  "operation_reconciled",
  "operation_restricted",
  "initial_decision_already_recorded",
  "request_payload_conflict",
  "command_id_conflict",
  "action_not_undoable",
  "legacy_action_binding_unavailable",
  "review_binding_mismatch",
  "source_grant_mismatch",
];

export function conflictCode(error: unknown): string | null {
  if (!(error instanceof ApiError) || error.status !== 409) return null;
  // CONTRACT.md section 9 fixes the error envelope, so the numeric status stays in `code` and
  // the semantic conflict reason arrives in `message`. Reading only `code` would show every
  // conflict as one vague sentence and hide why the decision was refused.
  for (const value of [error.message, error.code]) {
    if (CONFLICT_CODES.includes(value)) return value;
  }
  const descriptive = [error.message, error.code].find((value) => value && !/^\d+$/.test(value));
  return descriptive ?? "conflict";
}

function object(value: unknown, label: string): Record<string, unknown> {
  return recordValue(value, label);
}

async function request<T>(
  path: string,
  options: { method?: string; body?: unknown; signal?: AbortSignal; bearer?: string } = {},
): Promise<T> {
  const startedAtGeneration = sessionGeneration;
  const method = (options.method ?? "GET").toUpperCase();
  const controller = new AbortController();
  inflight.add(controller);
  const externalSignal = options.signal;
  const onExternalAbort = () => controller.abort();
  if (externalSignal) {
    if (externalSignal.aborted) controller.abort();
    else externalSignal.addEventListener("abort", onExternalAbort, { once: true });
  }

  const headers = new Headers();
  if (options.body !== undefined) headers.set("Content-Type", "application/json");
  // The key travels only on the one exchange request; every private read uses the cookie.
  if (options.bearer) headers.set("Authorization", `Bearer ${options.bearer}`);
  if (!SAFE_METHODS.has(method)) headers.set(CSRF_HEADER, "1");

  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      method,
      headers,
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      signal: controller.signal,
      credentials: "same-origin",
    });
  } catch (error) {
    if (isAbortError(error)) throw new ApiError("aborted", "The request was cancelled.", 0);
    throw new ApiError("network_error", "Could not reach Probation. Check that it is running and try again.");
  } finally {
    if (externalSignal) externalSignal.removeEventListener("abort", onExternalAbort);
    inflight.delete(controller);
  }

  if (startedAtGeneration !== sessionGeneration) {
    throw new ApiError("session_changed", "This sign-in ended before the data arrived.", 0);
  }

  if (!response.ok) {
    let code = String(response.status);
    let message =
      response.status === 401
        ? "Your sign-in is no longer valid. Enter your key again."
        : response.status === 403
          ? "Probation cannot show this account's data with the current sign-in."
          : "Probation could not complete that request.";
    try {
      const error = object(await response.json(), "error response");
      const detail = object(error.error, "error details");
      const detailCode = typeof detail.code === "string" ? detail.code : "";
      const detailMessage = typeof detail.message === "string" ? detail.message : "";
      if (detailCode === "connector_api_not_configured" || detailMessage === "connector_api_not_configured") {
        code = "connector_api_not_configured";
        message = "Probation's owner sign-in is not configured yet. Check the backend setup and restart the app.";
      } else {
        if (detailCode) code = detailCode;
        if (detailMessage) message = detailMessage;
      }
    } catch {
      // Keep the safe message if the server response is not the documented error shape.
    }
    throw new ApiError(code, message, response.status);
  }

  if (response.status === 204) return undefined as T;
  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    throw new ApiError("invalid_response", "Probation returned an unreadable response.");
  }
  return payload as T;
}

const query = (values: Record<string, string | number | undefined>) => {
  const params = new URLSearchParams();
  Object.entries(values).forEach(([key, value]) => {
    if (value !== undefined) params.set(key, String(value));
  });
  const text = params.toString();
  return text ? `?${text}` : "";
};

type Signal = AbortSignal | undefined;

export interface GmailSetupStatus {
  version: "v1";
  status: "not_connected" | "connected" | "awaiting_consent" | "succeeded" | "failed" | "unknown";
  connected: boolean;
  request_id?: string;
  reason?: string;
}

function decodeGmailSetup(value: unknown): GmailSetupStatus {
  const row = object(value, "Gmail connection status");
  const statuses = ["not_connected", "connected", "awaiting_consent", "succeeded", "failed", "unknown"];
  if (row.version !== "v1" || typeof row.status !== "string" || !statuses.includes(row.status)
      || typeof row.connected !== "boolean"
      || (row.request_id !== undefined && typeof row.request_id !== "string")
      || (row.reason !== undefined && row.reason !== null && typeof row.reason !== "string")
      || (row.connected && !["connected", "succeeded"].includes(row.status))) {
    throw new ApiError("invalid_response", "Probation returned an invalid connection status.");
  }
  return row as unknown as GmailSetupStatus;
}

export interface GmailConnectionSummary {
  connection_id: string;
  connection_ref: string;
  state: string;
}

export interface GmailConnectionCommandReceipt {
  request_id: string;
  command: "pause" | "resume" | "disconnect";
  status: string;
  status_url: string;
}

export interface GmailLifecycleStatus {
  request_id: string;
  type?: string;
  status: string;
  safe_code?: string | null;
}

function decodeGmailConnections(value: unknown): { connections: GmailConnectionSummary[] } {
  const row = object(value, "Gmail connections");
  if (!Array.isArray(row.connections)) {
    throw new ApiError("invalid_response", "Probation returned an invalid connection list.");
  }
  const connections = row.connections.map((entry) => {
    const item = object(entry, "Gmail connection");
    if (
      typeof item.connection_id !== "string"
      || item.connection_id.length === 0
      || typeof item.connection_ref !== "string"
      || item.connection_ref.length === 0
      || typeof item.state !== "string"
      || item.state.length === 0
    ) {
      throw new ApiError("invalid_response", "Probation returned an invalid connection list.");
    }
    return {
      connection_id: item.connection_id,
      connection_ref: item.connection_ref,
      state: item.state,
    };
  });
  return { connections };
}

function decodeGmailCommandReceipt(value: unknown): GmailConnectionCommandReceipt {
  const row = object(value, "Gmail connection command");
  if (
    typeof row.request_id !== "string"
    || !["pause", "resume", "disconnect"].includes(String(row.command))
    || typeof row.status !== "string"
    || typeof row.status_url !== "string"
  ) {
    throw new ApiError("invalid_response", "Probation returned an invalid command receipt.");
  }
  return row as unknown as GmailConnectionCommandReceipt;
}

function decodeGmailLifecycleStatus(value: unknown): GmailLifecycleStatus {
  const row = object(value, "Gmail connection status");
  if (
    typeof row.request_id !== "string"
    || typeof row.status !== "string"
    || (row.type !== undefined && typeof row.type !== "string")
    || (row.safe_code !== undefined && row.safe_code !== null && typeof row.safe_code !== "string")
  ) {
    throw new ApiError("invalid_response", "Probation returned an invalid command status.");
  }
  return row as unknown as GmailLifecycleStatus;
}

const gmailSetupPath = (kind: "read" | "write", requestId?: string): string =>
  `/gmail/setup/${kind}${requestId === undefined ? "" : `/${encodeURIComponent(requestId)}`}`;

export interface AccountSession {
  version: "v1";
  access_token: string;
  token_type: "bearer";
  expires_in: number;
  user: { email: string; owner_id: string };
}

function decodeAccountSession(value: unknown): AccountSession {
  const row = object(value, "account session");
  const user = row.user === undefined ? null : object(row.user, "account user");
  if (
    row.version !== "v1"
    || typeof row.access_token !== "string"
    || row.access_token.split(".").length !== 3
    || row.token_type !== "bearer"
    || typeof row.expires_in !== "number"
    || !Number.isFinite(row.expires_in)
    || row.expires_in <= 0
    || user === null
    || typeof user.email !== "string"
    || user.email.length === 0
    || typeof user.owner_id !== "string"
    || user.owner_id.length === 0
  ) {
    throw new ApiError("invalid_response", "Probation returned an invalid account session.");
  }
  return row as unknown as AccountSession;
}

export interface OwnerSessionInfo {
  version: "v1";
  authenticated: boolean;
  owner_id?: string;
  expires_in?: number;
  email?: string;
}

function decodeSessionState(value: unknown): OwnerSessionInfo {
  const row = object(value, "owner session");
  if (row.version !== "v1" || typeof row.authenticated !== "boolean") {
    throw new ApiError("invalid_response", "Probation returned an invalid session.");
  }
  if (row.authenticated) {
    if (
      typeof row.owner_id !== "string"
      || row.owner_id.trim().length === 0
      || typeof row.expires_in !== "number"
      || !Number.isFinite(row.expires_in)
      || row.expires_in <= 0
    ) {
      throw new ApiError("invalid_response", "Probation returned an invalid session.");
    }
  } else if (row.owner_id !== undefined || row.expires_in !== undefined) {
    throw new ApiError("invalid_response", "Probation returned an invalid session.");
  }
  return row as unknown as OwnerSessionInfo;
}

function decodeAuthenticatedSession(value: unknown): OwnerSessionInfo {
  const info = decodeSessionState(value);
  if (!info.authenticated) {
    throw new ApiError("invalid_response", "Probation did not start a session.");
  }
  return info;
}

export const apiClient = {
  async loginAccount(email: string, password: string): Promise<AccountSession> {
    const info = decodeAccountSession(
      await request<unknown>("/auth/login", { method: "POST", body: { email, password } }),
    );
    beginOwnerSession();
    return info;
  },
  async registerAccount(email: string, password: string): Promise<AccountSession> {
    const info = decodeAccountSession(
      await request<unknown>("/auth/register", { method: "POST", body: { email, password } }),
    );
    beginOwnerSession();
    return info;
  },
  async startSession(ownerKey: string, signal?: Signal): Promise<OwnerSessionInfo> {
    const info = decodeAuthenticatedSession(
      await request<unknown>("/session", { method: "POST", bearer: ownerKey, signal }),
    );
    beginOwnerSession();
    return info;
  },
  async getSession(signal?: Signal): Promise<OwnerSessionInfo> {
    return decodeSessionState(await request<unknown>("/session", { signal }));
  },
  async endSession(): Promise<void> {
    await request<unknown>("/session", { method: "DELETE" });
  },
  async getGmailSetup(signal?: Signal): Promise<GmailSetupStatus> {
    return decodeGmailSetup(await request<unknown>(gmailSetupPath("read"), { signal }));
  },
  async startGmailSetup(requestId: string): Promise<GmailSetupStatus> {
    return decodeGmailSetup(await request<unknown>(gmailSetupPath("read"), {
      method: "POST", body: { version: "v1", request_id: requestId },
    }));
  },
  async getGmailSetupRequest(requestId: string, signal?: Signal): Promise<GmailSetupStatus> {
    return decodeGmailSetup(await request<unknown>(gmailSetupPath("read", requestId), { signal }));
  },
  async getGmailWriteSetup(signal?: Signal): Promise<GmailSetupStatus> {
    return decodeGmailSetup(await request<unknown>(gmailSetupPath("write"), { signal }));
  },
  async startGmailWriteSetup(requestId: string): Promise<GmailSetupStatus> {
    return decodeGmailSetup(await request<unknown>(gmailSetupPath("write"), {
      method: "POST", body: { version: "v1", request_id: requestId },
    }));
  },
  async getGmailWriteSetupRequest(requestId: string, signal?: Signal): Promise<GmailSetupStatus> {
    return decodeGmailSetup(await request<unknown>(gmailSetupPath("write", requestId), { signal }));
  },
  async getGmailConnections(signal?: Signal): Promise<{ connections: GmailConnectionSummary[] }> {
    return decodeGmailConnections(await request<unknown>("/gmail/connections", { signal }));
  },
  async submitGmailConnectionCommand(
    connectionRef: string,
    requestId: string,
    command: "pause" | "resume" | "disconnect",
  ): Promise<GmailConnectionCommandReceipt> {
    return decodeGmailCommandReceipt(await request<unknown>(
      `/gmail/connections/${encodeURIComponent(connectionRef)}/commands`,
      { method: "POST", body: { version: "v1", request_id: requestId, command } },
    ));
  },
  async getGmailLifecycleStatus(requestId: string, signal?: Signal): Promise<GmailLifecycleStatus> {
    return decodeGmailLifecycleStatus(
      await request<unknown>(`/commands/${encodeURIComponent(requestId)}`, { signal }),
    );
  },
  async getBootstrap(signal?: Signal): Promise<{ version: string; profile: "private" | "synthetic"; auth_required: boolean; demo_login: boolean }> {
    return decodeBootstrap(await request<unknown>("/bootstrap", { signal }));
  },
  async getHealth(signal?: Signal): Promise<{ status: string; service: string; mode: string }> {
    return request("/health", { signal });
  },
  async getQueue(signal?: Signal): Promise<QueueResponse> {
    return decodeQueueResponse(await request<unknown>("/queue", { signal }));
  },
  async getWatching(signal?: Signal): Promise<{ items: QueueItem[]; total_count: number }> {
    return decodeWatchingResponse(await request<unknown>("/watching", { signal }));
  },
  async getItemDetail(id: string, signal?: Signal): Promise<ItemDetail> {
    return decodeItemDetail(await request<unknown>(`/items/${encodeURIComponent(id)}`, { signal }));
  },
  async reviewQueue(id: string, body: Record<string, unknown>, signal?: Signal): Promise<ReviewReceipt> {
    return decodeReviewReceipt(
      await request<unknown>(`/queue/${encodeURIComponent(id)}/review`, { method: "POST", body, signal }),
    );
  },
  async respondQueue(id: string, body: Record<string, unknown>, signal?: Signal): Promise<RespondReceipt> {
    return decodeRespondReceipt(
      await request<unknown>(`/queue/${encodeURIComponent(id)}/respond`, { method: "POST", body, signal }),
    );
  },
  async getResponseStatus(id: string, signal?: Signal): Promise<ResponseStatus> {
    return decodeResponseStatus(await request<unknown>(`/responses/${encodeURIComponent(id)}`, { signal }));
  },
  async getActions(signal?: Signal): Promise<{ actions: ActionItem[]; total_count: number }> {
    return decodeActionsResponse(await request<unknown>("/actions", { signal }));
  },
  async undoAction(id: string, requestId: string, signal?: Signal): Promise<{ request_id: string; status: string; status_url: string }> {
    const value = object(
      await request<unknown>(`/actions/${encodeURIComponent(id)}/undo`, {
        method: "POST",
        body: { version: "v2", request_id: requestId },
        signal,
      }),
      "request status",
    );
    if (typeof value.request_id !== "string" || value.status !== "recorded" || typeof value.status_url !== "string") {
      throw new ApiError("invalid_response", "Probation did not confirm that the request was recorded.");
    }
    return value as { request_id: string; status: string; status_url: string };
  },
  async getLicences(signal?: Signal): Promise<{ licences: LicenceItem[]; total_count: number }> {
    return decodeLicenceList(await request<unknown>("/permissions", { signal }));
  },
  async getReportCard(family: string, signal?: Signal): Promise<ReportCardResponse> {
    return decodeReportCard(await request<unknown>(`/report-card${query({ family })}`, { signal }));
  },
  async getMetricsSummary(signal?: Signal): Promise<MetricsSummaryResponse> {
    return decodeMetricsSummary(await request<unknown>("/metrics/summary", { signal }));
  },
  async getHabits(signal?: Signal): Promise<{ habits: HabitItem[] }> {
    return decodeHabitList(await request<unknown>("/habits", { signal }));
  },
  async demoAnalyze(text: string, signal?: Signal): Promise<DemoAnalyzeResponse> {
    return decodeDemoAnalyze(
      await request<unknown>("/demo/analyze", { method: "POST", body: { text }, signal }),
    );
  },
  async resetDemo(signal?: Signal): Promise<void> {
    await request<unknown>("/demo/reset", { method: "POST", signal });
  },
  async denyHabit(id: string, requestId: string, signal?: Signal): Promise<{ ok: boolean; command: AdminCommand }> {
    return decodeCommandEnvelope(
      await request<unknown>(`/habits/${encodeURIComponent(id)}/deny`, {
        method: "POST",
        body: { version: "v2", request_id: requestId },
        signal,
      }),
    );
  },
  async getChains(signal?: Signal): Promise<{ chains: ChainItem[] }> {
    return decodeChainList(await request<unknown>("/chains", { signal }));
  },
  async getExams(signal?: Signal): Promise<{ runs: ExamRunItem[] }> {
    return decodeExamRuns(await request<unknown>("/exams", { signal }));
  },
  /**
   * The exam command model is `extra="forbid"` and has no request_id field, so the ID
   * stays client-side for de-duplication only; the API assigns the durable command ID.
   */
  async runExam(
    classKey: string,
    action: string,
    attemptOrdinal = 0,
    signal?: Signal,
  ): Promise<{ ok: boolean; command: AdminCommand }> {
    return decodeCommandEnvelope(
      await request<unknown>("/exams/run", {
        method: "POST",
        body: { kind: "run_exam", class_key: classKey, action, attempt_ordinal: attemptOrdinal },
        signal,
      }),
    );
  },
  async getCommand(id: string, signal?: Signal): Promise<{ command: AdminCommand }> {
    const value = object(await request<unknown>(`/commands/${encodeURIComponent(id)}`, { signal }), "request");
    return { command: decodeAdminCommand("command" in value ? value.command : value) };
  },
  async getExposure(signal?: Signal): Promise<ExposureResponse> {
    return decodeExposure(await request<unknown>("/exposure", { signal }));
  },
  async getWebFacts(signal?: Signal): Promise<WebFactsResponse> {
    return decodeWebFacts(await request<unknown>("/web-facts", { signal }));
  },
  async verifyLedger(signal?: Signal): Promise<LedgerVerifyResponse> {
    return decodeLedgerVerify(await request<unknown>("/ledger/verify", { signal }));
  },
  async getSettings(signal?: Signal): Promise<SettingsResponse> {
    return decodeSettings(await request<unknown>("/settings", { signal }));
  },
  async getReplayState(signal?: Signal): Promise<ReplayStateResponse> {
    return decodeReplayState(await request<unknown>("/replay/state", { signal }));
  },
  // Frozen replay wire contract: the body carries request_id (and speed) only.
  async startReplay(requestId: string, signal?: Signal): Promise<Record<string, unknown>> {
    return object(await request<unknown>("/replay/start", { method: "POST", body: { request_id: requestId }, signal }), "replay request");
  },
  async pauseReplay(requestId: string, signal?: Signal): Promise<Record<string, unknown>> {
    return object(await request<unknown>("/replay/pause", { method: "POST", body: { request_id: requestId }, signal }), "replay request");
  },
  async setReplaySpeed(speed: 1 | 10 | 100, requestId: string, signal?: Signal): Promise<Record<string, unknown>> {
    if (![1, 10, 100].includes(speed)) throw new ApiError("invalid_speed", "Probation can only replay at 1x, 10x or 100x.");
    return object(
      await request<unknown>("/replay/speed", { method: "POST", body: { request_id: requestId, speed }, signal }),
      "replay request",
    );
  },
  async getBoard(pack: string, signal?: Signal): Promise<BoardResponse> {
    return decodeBoard(await request<unknown>(`/boards/${encodeURIComponent(pack)}`, { signal }));
  },
};
