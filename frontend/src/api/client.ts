/**
 * Typed API Client for Probation FastAPI Backend.
 * Strict rules:
 * - Uniform error parsing { error: { code, message } }
 * - Never silently substitute mock data when live API fails or is empty.
 * - Respects preview mode explicitly toggled by user.
 */

import {
  ActionItem,
  BoardResponse,
  ChainItem,
  ExamRunItem,
  ExposureResponse,
  HabitItem,
  LedgerVerifyResponse,
  LicenceItem,
  MetricsSummaryResponse,
  QueueResponse,
  ReplayStateResponse,
  ReportCardResponse,
  SettingsResponse,
  WebFactsResponse,
} from "./types";
import {
  MOCK_ACTIONS,
  MOCK_CHAINS,
  MOCK_EXAMS,
  MOCK_HABITS,
  MOCK_LICENCES,
  MOCK_METRICS,
  MOCK_QUEUE_ITEMS,
  MOCK_REPORT_CARD,
  MOCK_WEB_FACTS,
} from "./fixtures";

const API_BASE = "http://localhost:8000/api";

export class ApiError extends Error {
  code: string;
  constructor(code: string, message: string) {
    super(message);
    this.code = code;
    this.name = "ApiError";
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const url = `${API_BASE}${path}`;
  const headers = {
    "Content-Type": "application/json",
    ...(options.headers || {}),
  };

  const response = await fetch(url, { ...options, headers });
  if (!response.ok) {
    let errorCode = String(response.status);
    let errorMessage = response.statusText;
    try {
      const errorJson = await response.json();
      if (errorJson?.error) {
        errorCode = errorJson.error.code || errorCode;
        errorMessage = errorJson.error.message || errorMessage;
      }
    } catch {
      // Non-json response
    }
    throw new ApiError(errorCode, errorMessage);
  }

  return response.json() as Promise<T>;
}

export const apiClient = {
  // Mode flag: when true, user has deliberately switched to synthetic demo preview
  previewMode: false,

  setPreviewMode(enabled: boolean) {
    this.previewMode = enabled;
  },

  async getHealth(): Promise<{ status: string; service: string; mode: string }> {
    return request<{ status: string; service: string; mode: string }>("/health");
  },

  async getQueue(): Promise<QueueResponse> {
    if (this.previewMode) {
      return {
        items: MOCK_QUEUE_ITEMS,
        digests: [
          {
            class_key: "mail|recruiter|inquiry",
            action: "PREPARE_DECLINE_DRAFT",
            family: "email_action",
            count: 1,
            ask_count: 0,
            suggest_count: 1,
            items: ["prop-101"],
          },
          {
            class_key: "calendar|early_invite",
            action: "DECLINE",
            family: "calendar_action",
            count: 1,
            ask_count: 1,
            suggest_count: 0,
            items: ["prop-102"],
          },
        ],
        total_count: MOCK_QUEUE_ITEMS.length,
      };
    }
    return request<QueueResponse>("/queue");
  },

  async respondQueue(
    proposalId: string,
    response: "accept" | "reject" | "edit",
    editedAction?: string
  ): Promise<{ ok: boolean; id: string; response: string }> {
    if (this.previewMode) {
      return { ok: true, id: `preview-resp-${Date.now()}`, response };
    }
    return request<{ ok: boolean; id: string; response: string }>(`/queue/${proposalId}/respond`, {
      method: "POST",
      body: JSON.stringify({ response, edited_action: editedAction }),
    });
  },

  async getItemDetail(proposalId: string): Promise<Record<string, unknown>> {
    if (this.previewMode) {
      const found = MOCK_QUEUE_ITEMS.find((i) => i.id === proposalId) || MOCK_QUEUE_ITEMS[0];
      return {
        ...found,
        proposal_id: found.id,
        situation: {
          sender_key: found.sender_key,
          occurred_at: found.occurred_at,
          summary: found.summary,
        },
        evidence: {
          n_strong: 42,
          k_strong: 41,
          lb_strong: 0.894,
          n_recent: 14,
        },
      };
    }
    return request<Record<string, unknown>>(`/items/${proposalId}`);
  },

  async getActions(): Promise<{ actions: ActionItem[]; total_count: number }> {
    if (this.previewMode) {
      return { actions: MOCK_ACTIONS, total_count: MOCK_ACTIONS.length };
    }
    return request<{ actions: ActionItem[]; total_count: number }>("/actions");
  },

  async undoAction(actionId: string): Promise<{ ok: boolean; status: string }> {
    if (this.previewMode) {
      return { ok: true, status: "UNDO_REQUESTED" };
    }
    return request<{ ok: boolean; status: string }>(`/actions/${actionId}/undo`, {
      method: "POST",
    });
  },

  async getLicences(): Promise<{ licences: LicenceItem[]; total_count: number }> {
    if (this.previewMode) {
      return { licences: MOCK_LICENCES, total_count: MOCK_LICENCES.length };
    }
    return request<{ licences: LicenceItem[]; total_count: number }>("/licences");
  },

  async getReportCard(family: string): Promise<ReportCardResponse> {
    if (this.previewMode) {
      return MOCK_REPORT_CARD;
    }
    return request<ReportCardResponse>(`/report-card?family=${encodeURIComponent(family)}`);
  },

  async getMetricsSummary(): Promise<MetricsSummaryResponse> {
    if (this.previewMode) {
      return MOCK_METRICS;
    }
    return request<MetricsSummaryResponse>("/metrics/summary");
  },

  async getHabits(): Promise<{ habits: HabitItem[] }> {
    if (this.previewMode) {
      return { habits: MOCK_HABITS };
    }
    return request<{ habits: HabitItem[] }>("/habits");
  },

  async denyHabit(habitId: string): Promise<{ ok: boolean; habit_id: string; denied: boolean }> {
    if (this.previewMode) {
      return { ok: true, habit_id: habitId, denied: true };
    }
    return request<{ ok: boolean; habit_id: string; denied: boolean }>(`/habits/${habitId}/deny`, {
      method: "POST",
    });
  },

  async getChains(): Promise<{ chains: ChainItem[] }> {
    if (this.previewMode) {
      return { chains: MOCK_CHAINS };
    }
    return request<{ chains: ChainItem[] }>("/chains");
  },

  async getExams(): Promise<{ runs: ExamRunItem[] }> {
    if (this.previewMode) {
      return { runs: MOCK_EXAMS };
    }
    return request<{ runs: ExamRunItem[] }>("/exams");
  },

  async runExam(classKey: string, action: string): Promise<{ ok: boolean; run_id: string }> {
    if (this.previewMode) {
      return { ok: true, run_id: `exam-prev-${Date.now()}` };
    }
    return request<{ ok: boolean; run_id: string }>("/exams/run", {
      method: "POST",
      body: JSON.stringify({ class_key: classKey, action }),
    });
  },

  async getExposure(): Promise<ExposureResponse> {
    if (this.previewMode) {
      return {
        calls: 24,
        total_cost_usd: 0.048,
        breakdown: [
          {
            call_kind: "reader",
            model_id: "nvidia/nemotron-mini-4b-instruct",
            calls: 20,
            tokens_in: 4800,
            tokens_out: 1200,
            cost_usd: 0.04,
          },
        ],
      };
    }
    return request<ExposureResponse>("/exposure");
  },

  async getWebFacts(): Promise<WebFactsResponse> {
    if (this.previewMode) {
      return MOCK_WEB_FACTS;
    }
    return request<WebFactsResponse>("/web-facts");
  },

  async verifyLedger(): Promise<LedgerVerifyResponse> {
    if (this.previewMode) {
      return {
        ok: true,
        seq: null,
        length: 482,
        head_hash: "a4c28e81f9b34208a5cb72837f40192df78923a1029487b320984ef1928374a2",
      };
    }
    return request<LedgerVerifyResponse>("/ledger/verify");
  },

  async getSettings(): Promise<SettingsResponse> {
    return request<SettingsResponse>("/settings");
  },

  async getReplayState(): Promise<ReplayStateResponse> {
    if (this.previewMode) {
      return {
        running: false,
        speed: 1.0,
        simulated_date: "2026-03-01T12:00:00Z",
        mode: "replay",
      };
    }
    return request<ReplayStateResponse>("/replay/state");
  },

  async startReplay(): Promise<{ ok: boolean }> {
    return request<{ ok: boolean }>("/replay/start", { method: "POST" });
  },

  async pauseReplay(): Promise<{ ok: boolean }> {
    return request<{ ok: boolean }>("/replay/pause", { method: "POST" });
  },

  async setReplaySpeed(speed: number): Promise<{ ok: boolean }> {
    return request<{ ok: boolean }>("/replay/speed", {
      method: "POST",
      body: JSON.stringify({ speed }),
    });
  },

  async getBoard(pack: string): Promise<BoardResponse> {
    if (this.previewMode) {
      if (pack === "radar") {
        return {
          pack: "radar",
          active: true,
          entries: [
            {
              id: "radar-1",
              pack: "radar",
              entity: "Anthropic API update",
              status: "WATCHING",
              sources: [{ title: "Anthropic docs", url: "https://docs.anthropic.com" }],
              updated_at: new Date().toISOString(),
            },
          ],
        };
      }
      return { pack, active: false, entries: [] };
    }
    return request<BoardResponse>(`/boards/${encodeURIComponent(pack)}`);
  },
};
