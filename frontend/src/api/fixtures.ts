/**
 * Synthetic demonstration data for explicit Preview Mode (Persona: Meena).
 * Invariant: Never silently substituted for live API responses.
 */

import {
  ActionItem,
  ChainItem,
  ExamRunItem,
  HabitItem,
  LicenceItem,
  MetricsSummaryResponse,
  QueueItem,
  ReportCardResponse,
  WebFactsResponse,
} from "./types";

export const MOCK_QUEUE_ITEMS: QueueItem[] = [
  {
    id: "prop-101",
    situation_id: "sit-101",
    family: "email_action",
    class_key: "mail|recruiter|inquiry",
    action: "PREPARE_DECLINE_DRAFT",
    probs: { PREPARE_DECLINE_DRAFT: 0.88, ARCHIVE: 0.08, SUGGEST_CALL: 0.04 },
    p_max: 0.88,
    novelty: 0.05,
    licence_level: 1,
    cap: 2,
    gate: "SUGGEST",
    reasons: ["familiar_pattern", "recruiter_domain_matched"],
    params: { tone: "polite_no", template: "graduating_next_year" },
    explanation: {
      top_clues: [
        "Sender identified as third-party tech recruiter",
        "Subject contains 'SWE Internship 2027'",
        "Historical response: 18 of 19 declined with standard polite note",
      ],
      similar_cases: [
        {
          situation_id: "sit-044",
          similarity: 0.94,
          action_taken: "PREPARE_DECLINE_DRAFT",
          summary: "Recruiter inquiry from TechStaff Partners",
        },
        {
          situation_id: "sit-012",
          similarity: 0.89,
          action_taken: "PREPARE_DECLINE_DRAFT",
          summary: "Apex Systems reach-out",
        },
      ],
      summary_reason: "Matches your established habit of declining external recruiters while in school.",
    },
    web: {
      status: "confirmed_official",
      cap: 2,
      source_ids: ["https://talentmatch.io"],
    },
    audit_holdout: false,
    proposed_at: "2026-03-01T09:15:00Z",
    sender_key: "recruiter@talentmatch.io",
    occurred_at: "2026-03-01T09:12:00Z",
    summary: "Senior Engineering Recruiter inquiry regarding 2027 rotation program.",
    draft: {
      body_text: "Hi Alex,\n\nThanks for reaching out! I'm currently focused on completing my degree and am not exploring new opportunities right now. Best of luck with the search!\n\nBest,\nMeena",
      needs_user_input: false,
    },
  },
  {
    id: "prop-102",
    situation_id: "sit-102",
    family: "calendar_action",
    class_key: "calendar|early_invite",
    action: "DECLINE",
    probs: { DECLINE: 0.76, ACCEPT: 0.24 },
    p_max: 0.76,
    novelty: 0.12,
    licence_level: 1,
    cap: 2,
    gate: "ASK",
    reasons: ["starts_before_9am", "recent_habit_shift"],
    params: { reason: "prior_conflict" },
    explanation: {
      top_clues: [
        "Start time is 8:00 AM (before 9:00 AM personal quiet window)",
        "Organizer: peer student study group",
      ],
      summary_reason: "Your recent habit shift shows you accepted 2 early invites last week. Asking for confirmation.",
    },
    web: { status: "not_checked" },
    audit_holdout: true,
    proposed_at: "2026-03-01T08:30:00Z",
    sender_key: "study-lead@university.edu",
    occurred_at: "2026-03-01T08:28:00Z",
    summary: "Early Morning Algorithms Review (8:00 AM - 9:00 AM)",
    draft: null,
  },
];

export const MOCK_ACTIONS: ActionItem[] = [
  {
    id: "act-201",
    proposal_id: "prop-098",
    pack: "mail",
    type: "ARCHIVE",
    params: { message_id: "msg-newsletter-99" },
    level_required: 2,
    recallable: true,
    status: "DONE",
    hold_until: null,
    undo: { original_folder: "INBOX", message_id: "msg-newsletter-99" },
    created_at: "2026-03-01T07:45:00Z",
    updated_at: "2026-03-01T07:45:00Z",
    executed_at: "2026-03-01T07:45:01Z",
    class_key: "mail|automated|newsletter",
    family: "email_action",
    summary: "Archived daily Substack digest 'The Morning Paper'",
  },
  {
    id: "act-202",
    proposal_id: "prop-099",
    pack: "calendar",
    type: "MOVE_EVENT",
    params: { event_id: "evt-design-sync", new_start: "2026-03-01T15:00:00Z" },
    level_required: 2,
    recallable: true,
    status: "HELD",
    hold_until: "2026-03-01T10:10:00Z",
    undo: { original_start: "2026-03-01T14:00:00Z" },
    created_at: "2026-03-01T10:00:00Z",
    updated_at: "2026-03-01T10:00:00Z",
    executed_at: null,
    class_key: "calendar|peer_sync",
    family: "calendar_action",
    summary: "Moving peer sync by 1 hr to resolve overlap. 10m cancellation window active.",
  },
];

export const MOCK_LICENCES: LicenceItem[] = [
  {
    class_key: "mail|automated|newsletter",
    action: "ARCHIVE",
    level: 3,
    lower_bound: 0.985,
    n_strong: 148,
    k_strong: 148,
    n_all: 160,
    k_all: 160,
    n_recent: 32,
    exam_run_id: "exam-991",
    valid_until: "2026-03-31T00:00:00Z",
    reasons: ["promoted_to_level_3", "strong_agreement_proven"],
    drift: { cusum: 0.0, baseline_err: 0.02, last_alarm_at: null },
    history: [
      { seq: 412, created_at: "2026-02-15T00:00:00Z", old_level: 2, new_level: 3, reason: "passed_trick_exam" },
      { seq: 210, created_at: "2026-01-20T00:00:00Z", old_level: 1, new_level: 2, reason: "n_strong_exceeded_40" },
    ],
  },
  {
    class_key: "mail|recruiter|inquiry",
    action: "PREPARE_DECLINE_DRAFT",
    level: 1,
    lower_bound: 0.894,
    n_strong: 42,
    k_strong: 41,
    n_all: 48,
    k_all: 46,
    n_recent: 14,
    exam_run_id: null,
    valid_until: "2026-03-31T00:00:00Z",
    reasons: ["waiting_for_counterfactual_exam"],
    drift: { cusum: 0.4, baseline_err: 0.03, last_alarm_at: null },
    history: [
      { seq: 301, created_at: "2026-02-01T00:00:00Z", old_level: 0, new_level: 1, reason: "l1_threshold_met" },
    ],
  },
];

export const MOCK_REPORT_CARD: ReportCardResponse = {
  family: "email_action",
  as_of: "2026-03-01T00:00:00Z",
  total_proposals: 184,
  total_evaluated: 172,
  same: 164,
  different: 8,
  would_ask: 22,
  censored: 12,
  accuracy: 0.9535,
  scope: "family_summary",
};

export const MOCK_METRICS: MetricsSummaryResponse = {
  proposals_total: 214,
  asks: 38,
  suggestions: 54,
  automatic_actions: 122,
  agreement_rate: 0.953,
  weekly_series: [
    { week: "2026-W05", asks: 12, suggestions: 8, auto_actions: 14, total: 34 },
    { week: "2026-W06", asks: 10, suggestions: 14, auto_actions: 26, total: 50 },
    { week: "2026-W07", asks: 8, suggestions: 16, auto_actions: 38, total: 62 },
    { week: "2026-W08", asks: 8, suggestions: 16, auto_actions: 44, total: 68 },
  ],
  alarms: [],
};

export const MOCK_HABITS: HabitItem[] = [
  {
    id: "hab-01",
    family: "email_action",
    clue: "sender_domain",
    clue_value: "substack.com",
    action: "ARCHIVE",
    k: 31,
    n: 31,
    lift: 3.2,
    q_value: 0.0001,
    statement: "You consistently archive automated Substack newsletters unread.",
    examples: [],
    status: "active",
    denied: false,
    created_at: "2026-02-20T10:00:00Z",
  },
];

export const MOCK_CHAINS: ChainItem[] = [
  {
    id: "ch-01",
    trigger_class_key: "mail|faculty|deadline",
    follow_action: "BLOCK_TIME",
    k: 18,
    n: 20,
    base_rate: 0.25,
    lift: 3.6,
    status: "active",
    created_at: "2026-02-22T10:00:00Z",
  },
];

export const MOCK_EXAMS: ExamRunItem[] = [
  {
    id: "exam-991",
    class_key: "mail|automated|newsletter",
    action: "ARCHIVE",
    level_tested: 3,
    started_at: "2026-02-15T02:00:00Z",
    finished_at: "2026-02-15T02:02:00Z",
    n_cases: 6,
    invariance_flip_rate: 0.0,
    critical_violations: 0,
    passed: true,
    details: { reason: "passed_all_invariance_checks" },
    cases: [
      {
        id: "ec-1",
        situation_id: "sit-news-1",
        operator: "keyword_injection",
        expectation: "invariant",
        edit_valid: true,
        decision_before: "ARCHIVE",
        decision_after: "ARCHIVE",
        violated: false,
        critical: false,
      },
    ],
  },
];

export const MOCK_WEB_FACTS: WebFactsResponse = {
  total_calls: 14,
  total_credits: 14.0,
  queries: [
    {
      id: "tav-901",
      endpoint: "search",
      query: "talentmatch.io official recruiting",
      credits: 1.0,
      ok: true,
      latency_ms: 320,
      created_at: "2026-03-01T09:12:30Z",
    },
  ],
  entities: [
    {
      domain: "talentmatch.io",
      status: "confirmed_official",
      facts: { domain_in_results: true },
      sources: [{ title: "TalentMatch Careers", url: "https://talentmatch.io" }],
      fetched_at: "2026-03-01T09:12:32Z",
    },
  ],
};
