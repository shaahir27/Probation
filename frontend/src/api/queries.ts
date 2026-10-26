/**
 * TanStack Query surface for every private read.
 *
 * Why this exists: the previous app hand-rolled one `Promise.all` per screen, so
 * there was no cache, no stale marking, no cancellation and no per-view refetch.
 * Keys never contain the owner credential — the token is only ever a bearer header.
 */

import { useQuery, type QueryClient, type QueryKey } from "@tanstack/react-query";
import { apiClient, isLockedError } from "./client";

const MINUTE = 60_000;

/** How long a panel may claim to be current before it is marked out of date. */
export const FRESH_FOR_MS = 2 * MINUTE;
export const STALE_AFTER_MS = 5 * MINUTE;

export const queryKeys = {
  bootstrap: ["bootstrap"] as const,
  queue: ["private", "queue"] as const,
  watching: ["private", "watching"] as const,
  actions: ["private", "actions"] as const,
  permissions: ["private", "permissions"] as const,
  reportCard: (family: string) => ["private", "report-card", family] as const,
  metrics: ["private", "metrics"] as const,
  habits: ["private", "habits"] as const,
  chains: ["private", "chains"] as const,
  exams: ["private", "exams"] as const,
  item: (id: string) => ["private", "item", id] as const,
  response: (id: string) => ["private", "response", id] as const,
  command: (id: string) => ["private", "command", id] as const,
  replay: ["private", "replay-state"] as const,
  board: (pack: string) => ["private", "board", pack] as const,
  exposure: ["private", "exposure"] as const,
  webFacts: ["private", "web-facts"] as const,
  ledger: ["private", "ledger"] as const,
  settings: ["private", "settings"] as const,
};

type Reader<T> = (signal: AbortSignal) => Promise<T>;

interface ReadConfig {
  enabled: boolean;
  refetchInterval?: number | false;
  pollUntilSettled?: boolean;
}

function retryDecision(failureCount: number, error: unknown): boolean {
  // A cancelled read, a locked session or an unreadable payload is never retried:
  // retrying an unknown result could duplicate an effect.
  if (isLockedError(error)) return false;
  const code = typeof error === "object" && error !== null && "code" in error ? String((error as { code: unknown }).code) : "";
  if (code === "aborted" || code === "session_changed" || code === "invalid_response") return false;
  return failureCount < 1;
}

/** One cancellable read with honest error, stale and disabled states. */
export function useRead<T>(key: QueryKey, reader: Reader<T>, config: ReadConfig) {
  return useQuery({
    queryKey: key,
    queryFn: ({ signal }) => reader(signal),
    enabled: config.enabled,
    retry: retryDecision,
    staleTime: FRESH_FOR_MS,
    refetchOnWindowFocus: false,
    refetchInterval: config.refetchInterval ?? false,
  });
}

export const useBootstrapRead = () =>
  useQuery({
    queryKey: queryKeys.bootstrap,
    queryFn: ({ signal }) => apiClient.getBootstrap(signal),
    retry: 1,
    staleTime: FRESH_FOR_MS,
  });

export const useQueueRead = (enabled: boolean) => useRead(queryKeys.queue, (signal) => apiClient.getQueue(signal), { enabled });
export const useWatchingRead = (enabled: boolean) =>
  useRead(queryKeys.watching, (signal) => apiClient.getWatching(signal), { enabled });
export const useActionsRead = (enabled: boolean) =>
  useRead(queryKeys.actions, (signal) => apiClient.getActions(signal), { enabled, refetchInterval: enabled ? 10_000 : false });
export const usePermissionsRead = (enabled: boolean) =>
  useRead(queryKeys.permissions, (signal) => apiClient.getLicences(signal), { enabled });
export const useHabitsRead = (enabled: boolean) => useRead(queryKeys.habits, (signal) => apiClient.getHabits(signal), { enabled });
export const useChainsRead = (enabled: boolean) => useRead(queryKeys.chains, (signal) => apiClient.getChains(signal), { enabled });
export const useExamsRead = (enabled: boolean) => useRead(queryKeys.exams, (signal) => apiClient.getExams(signal), { enabled });
export const useMetricsRead = (enabled: boolean) =>
  useRead(queryKeys.metrics, (signal) => apiClient.getMetricsSummary(signal), { enabled });
export const useReportCardRead = (family: string, enabled: boolean) =>
  useRead(queryKeys.reportCard(family), (signal) => apiClient.getReportCard(family, signal), { enabled });
export const useExposureRead = (enabled: boolean) => useRead(queryKeys.exposure, (signal) => apiClient.getExposure(signal), { enabled });
export const useWebFactsRead = (enabled: boolean) =>
  useRead(queryKeys.webFacts, (signal) => apiClient.getWebFacts(signal), { enabled });
export const useLedgerRead = (enabled: boolean) => useRead(queryKeys.ledger, (signal) => apiClient.verifyLedger(signal), { enabled });
export const useSettingsRead = (enabled: boolean) => useRead(queryKeys.settings, (signal) => apiClient.getSettings(signal), { enabled });
export const useItemRead = (id: string | null, enabled: boolean) =>
  useRead(id ? queryKeys.item(id) : queryKeys.item("none"), (signal) => apiClient.getItemDetail(id ?? "", signal), {
    enabled: enabled && id !== null,
  });
export const useBoardRead = (pack: string, enabled: boolean) =>
  useRead(queryKeys.board(pack), (signal) => apiClient.getBoard(pack, signal), { enabled });
export const useResponseStatusRead = (requestId: string | null, enabled: boolean) =>
  useRead(requestId ? queryKeys.response(requestId) : queryKeys.response("none"), (signal) => apiClient.getResponseStatus(requestId ?? "", signal), {
    enabled: enabled && requestId !== null,
    refetchInterval: enabled ? 4_000 : false,
  });
export const useCommandRead = (commandId: string | null, enabled: boolean) =>
  useRead(commandId ? queryKeys.command(commandId) : queryKeys.command("none"), (signal) => apiClient.getCommand(commandId ?? "", signal), {
    enabled: enabled && commandId !== null,
    refetchInterval: enabled ? 5_000 : false,
  });

const SETTLED = new Set(["succeeded", "failed", "cancelled", "undone", "not_required"]);

/** Only the server's own terminal statuses stop polling. */
export function isSettledStatus(status: unknown): boolean {
  return typeof status === "string" && SETTLED.has(status);
}

export const useReplayStateRead = (enabled: boolean) =>
  useRead(queryKeys.replay, (signal) => apiClient.getReplayState(signal), { enabled, refetchInterval: enabled ? 5_000 : false });

/**
 * Shared panel state for the primary destinations: exactly one loading, error,
 * locked or stale verdict across the reads a screen actually depends on.
 */
export interface PanelStatus {
  isLoading: boolean;
  isFetching: boolean;
  errorMessage: string | null;
  isLocked: boolean;
  isStale: boolean;
  updatedAt: number | null;
}

type ReadLike = {
  data: unknown;
  error: unknown;
  isLoading: boolean;
  isFetching: boolean;
  dataUpdatedAt: number;
  status: string;
};

export function panelStatus(
  reads: ReadLike[],
  now: number = Date.now(),
  staleAfterMs: number = STALE_AFTER_MS,
): PanelStatus {
  const loaded = reads.filter((read) => read.data !== undefined);
  const failed = reads.filter((read) => read.error !== null && read.error !== undefined);
  const locked = failed.some((read) => isLockedError(read.error));
  const updatedAt = loaded.length ? Math.min(...loaded.map((read) => read.dataUpdatedAt)) : null;
  const refreshFailed = loaded.length > 0 && failed.length > 0;
  const tooOld = updatedAt !== null && now - updatedAt > staleAfterMs;
  return {
    isLoading: reads.some((read) => read.isLoading),
    isFetching: reads.some((read) => read.isFetching),
    errorMessage: failed.length ? messageOf(failed[0].error) : null,
    isLocked: locked,
    // Data is stale when a refresh failed inside this session, or when the newest
    // successful read is older than the freshness window.
    isStale: loaded.length > 0 && (refreshFailed || tooOld),
    updatedAt,
  };
}

function messageOf(error: unknown): string {
  if (error instanceof Error && error.message) return error.message;
  return "This information is unavailable right now.";
}

/** Everything a confirmed state change invalidates: queue, detail, actions, permissions, reports. */
export function invalidatePrivateData(client: QueryClient): void {
  client.invalidateQueries({ queryKey: ["private", "queue"] });
  client.invalidateQueries({ queryKey: ["private", "watching"] });
  client.invalidateQueries({ queryKey: ["private", "actions"] });
  client.invalidateQueries({ queryKey: ["private", "permissions"] });
  client.invalidateQueries({ queryKey: ["private", "item"] });
  client.invalidateQueries({ queryKey: ["private", "report-card"] });
  client.invalidateQueries({ queryKey: ["private", "metrics"] });
}

/** Hard stop for logout: no cached private row survives the session change. */
export function clearPrivateCache(client: QueryClient): void {
  client.cancelQueries({ queryKey: ["private"] });
  client.removeQueries({ queryKey: ["private"] });
}
