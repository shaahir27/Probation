import { useState } from "react";
import {
  ReportCardResponse,
  MetricsSummaryResponse,
  HabitItem,
  ChainItem,
  ExamRunItem,
} from "../api/types";
import { Badge } from "../components/common/Badge";
import { Button } from "../components/common/Button";

interface InsightsViewProps {
  reportCard: ReportCardResponse | null;
  metrics: MetricsSummaryResponse | null;
  habits: HabitItem[];
  chains: ChainItem[];
  exams: ExamRunItem[];
  onDenyHabit: (habitId: string) => Promise<void>;
  onRunExam: (classKey: string, action: string) => Promise<void>;
}

export function InsightsView({
  reportCard,
  metrics,
  habits,
  chains,
  exams,
  onDenyHabit,
  onRunExam,
}: InsightsViewProps) {
  const [activeSubTab, setActiveSubTab] = useState<"report" | "metrics" | "habits" | "chains" | "exams">("report");

  return (
    <div className="space-y-6">
      {/* Sub-tab navigation */}
      <div className="flex flex-wrap gap-2 border-b border-line pb-3">
        {[
          { id: "report", label: "Report Card" },
          { id: "metrics", label: "Metrics & Trends" },
          { id: "habits", label: `Habits (${habits.length})` },
          { id: "chains", label: `Chains (${chains.length})` },
          { id: "exams", label: `Exams (${exams.length})` },
        ].map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveSubTab(tab.id as typeof activeSubTab)}
            className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
              activeSubTab === tab.id
                ? "bg-surfaceRaised text-brand border border-brand/30 shadow-sm"
                : "text-ink-secondary hover:text-ink hover:bg-surfaceSubtle"
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Sub-view: Report Card */}
      {activeSubTab === "report" && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="text-base font-bold text-ink">Driving Test: Backtest Summary</h3>
            <Badge variant="subtle">Family Summary: {reportCard?.family || "email_action"}</Badge>
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
            <div className="p-4 rounded-xl bg-surface border border-line">
              <span className="text-xs text-ink-tertiary">Same as You</span>
              <div className="text-xl font-bold text-status-success mt-1">{reportCard?.same ?? 0}</div>
            </div>
            <div className="p-4 rounded-xl bg-surface border border-line">
              <span className="text-xs text-ink-tertiary">Different</span>
              <div className="text-xl font-bold text-status-danger mt-1">{reportCard?.different ?? 0}</div>
            </div>
            <div className="p-4 rounded-xl bg-surface border border-line">
              <span className="text-xs text-ink-tertiary">Would Have Asked</span>
              <div className="text-xl font-bold text-brand mt-1">{reportCard?.would_ask ?? 0}</div>
            </div>
            <div className="p-4 rounded-xl bg-surface border border-line">
              <span className="text-xs text-ink-tertiary">Censored / Unresolved</span>
              <div className="text-xl font-bold text-ink-secondary mt-1">{reportCard?.censored ?? 0}</div>
            </div>
          </div>

          <div className="p-4 rounded-xl bg-surfaceSubtle border border-line text-xs text-ink-secondary">
            Note: As specified in CONTRACT.md, this report card aggregates outcomes across the entire family. Task-specific agreement scores require an approved contract extension and are marked as unavailable rather than inferred.
          </div>
        </div>
      )}

      {/* Sub-view: Metrics */}
      {activeSubTab === "metrics" && (
        <div className="space-y-4">
          <h3 className="text-base font-bold text-ink">Operational Trends</h3>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <div className="p-4 rounded-xl bg-surface border border-line">
              <span className="text-xs text-ink-tertiary">Total Proposals</span>
              <div className="text-2xl font-bold text-ink mt-1">{metrics?.proposals_total ?? 0}</div>
            </div>
            <div className="p-4 rounded-xl bg-surface border border-line">
              <span className="text-xs text-ink-tertiary">Autonomous Actions</span>
              <div className="text-2xl font-bold text-status-success mt-1">{metrics?.automatic_actions ?? 0}</div>
            </div>
            <div className="p-4 rounded-xl bg-surface border border-line">
              <span className="text-xs text-ink-tertiary">Human Interventions</span>
              <div className="text-2xl font-bold text-brand mt-1">{metrics?.asks ?? 0}</div>
            </div>
          </div>

          <div className="p-4 rounded-xl bg-surface border border-line space-y-2">
            <h4 className="text-xs font-semibold uppercase tracking-wider text-ink-secondary">
              Weekly Volume Summary
            </h4>
            <div className="divide-y divide-line">
              {metrics?.weekly_series.map((w) => (
                <div key={w.week} className="py-2 flex items-center justify-between text-xs">
                  <span className="font-mono text-ink">{w.week}</span>
                  <div className="flex gap-4 text-ink-secondary">
                    <span>Asks: {w.asks}</span>
                    <span>Suggestions: {w.suggestions}</span>
                    <span className="text-status-success font-semibold">Auto: {w.auto_actions}</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Sub-view: Habits */}
      {activeSubTab === "habits" && (
        <div className="space-y-3">
          <div className="text-xs text-ink-secondary">
            Mined habits describe repeated past behaviors. They never grant autonomy on their own.
          </div>
          {habits.map((h) => (
            <div key={h.id} className="p-4 rounded-xl bg-surface border border-line flex items-center justify-between gap-4">
              <div>
                <p className="text-sm font-medium text-ink">{h.statement}</p>
                <div className="text-xs text-ink-tertiary mt-1">
                  Observed {h.k} of {h.n} times (lift {h.lift.toFixed(1)}x)
                </div>
              </div>
              {!h.denied && (
                <Button size="sm" variant="secondary" onClick={() => onDenyHabit(h.id)} className="text-xs">
                  Dismiss pattern
                </Button>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Sub-view: Chains */}
      {activeSubTab === "chains" && (
        <div className="space-y-3">
          <div className="text-xs text-ink-secondary">
            Multi-step patterns discovered across packs. Each step requires separate permission.
          </div>
          {chains.map((c) => (
            <div key={c.id} className="p-4 rounded-xl bg-surface border border-line space-y-2">
              <div className="flex items-center gap-2">
                <span className="text-xs font-semibold text-brand">{c.trigger_class_key}</span>
                <span className="text-ink-tertiary">→ then</span>
                <span className="text-sm font-bold text-ink">{c.follow_action}</span>
              </div>
              <div className="text-xs text-ink-tertiary">
                Followed in {c.k} of {c.n} instances (lift {c.lift.toFixed(1)}x)
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Sub-view: Exams */}
      {activeSubTab === "exams" && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="text-base font-bold text-ink">Trick-Question Exams</h3>
            <Button
              variant="secondary"
              size="sm"
              onClick={() => onRunExam("mail|recruiter|inquiry", "PREPARE_DECLINE_DRAFT")}
            >
              Run Diagnostic Exam
            </Button>
          </div>
          {exams.map((ex) => (
            <div key={ex.id} className="p-4 rounded-xl bg-surface border border-line space-y-2">
              <div className="flex items-center justify-between">
                <div>
                  <span className="text-xs font-semibold text-brand">{ex.class_key}</span>
                  <div className="text-sm font-bold text-ink">Action: {ex.action}</div>
                </div>
                <Badge variant={ex.passed ? "success" : "danger"}>
                  {ex.passed ? "Passed" : "Failed"}
                </Badge>
              </div>
              <div className="text-xs text-ink-tertiary">
                Tested Level {ex.level_tested} · Cases: {ex.n_cases} · Finished: {ex.finished_at || "In progress"}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
