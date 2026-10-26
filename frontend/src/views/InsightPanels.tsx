import { useState } from "react";
import { ArrowRight, Filter } from "lucide-react";
import { ChainItem, ExamRunItem, HabitItem, MetricsSummaryResponse, ReportCardResponse, TaskReportItem } from "../api/types";
import { Button } from "../components/common/Button";
import { StatePanel } from "../components/common/StatePanel";

/** Counts, never a global trust score. Percentages name their own cohort. */
export function ReportCardPanel({ reportCard }: { reportCard: ReportCardResponse | null }) {
  if (reportCard === null) {
    return (
      <StatePanel
        state="empty"
        title="Report card is unavailable"
        description="Probation has no measured results to show for this account yet."
      />
    );
  }
  const total = reportCard.total_evaluated;
  const pct = (value: number) => (total > 0 ? Math.floor((value / total) * 100) : 0);
  const tasks = (reportCard.tasks ?? []).filter((task) => (task.action ?? "").toUpperCase() !== "ABSTAIN");
  const [filter, setFilter] = useState<"all" | "attention" | "stable">("all");
  const attention = (task: TaskReportItem) => task.status === "needs_attention" || task.needs_attention === true;
  const visible = tasks.filter((task) => (filter === "attention" ? attention(task) : filter === "stable" ? !attention(task) : true));

  return (
    <div className="space-y-5">
      <section aria-labelledby="report-title" className="space-y-3 rounded-2xl border border-line bg-surface p-5">
        <h2 id="report-title" className="font-serif text-xl">
          Historical agreement
        </h2>
        <p className="text-sm text-ink-secondary">
          Scope: {reportCard.family} · evaluated {total} of {reportCard.total_proposals} recorded situations
          {reportCard.as_of ? ` · as of ${reportCard.as_of}` : ""}.
        </p>
        <ul className="flex flex-wrap gap-x-5 gap-y-1 text-sm">
          <li>Same as you: <strong>{reportCard.same}</strong> ({pct(reportCard.same)}%)</li>
          <li>Would have asked: <strong>{reportCard.would_ask}</strong> ({pct(reportCard.would_ask)}%)</li>
          <li>Different: <strong className="text-status-danger">{reportCard.different}</strong> ({pct(reportCard.different)}%)</li>
          <li>No answer yet: <strong className="text-ink-tertiary">{reportCard.censored}</strong></li>
        </ul>
        <p className="text-xs text-ink-tertiary">
          Based only on what was known at the time. Recent items have no answer yet and are left out of the denominator.
        </p>
      </section>

      <section aria-labelledby="tasks-title" className="space-y-3">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <h2 id="tasks-title" className="text-base font-medium">
            Task by task
          </h2>
          <div role="group" aria-label="Filter tasks" className="flex flex-wrap gap-2">
            {([
              { id: "all", label: `All (${tasks.length})` },
              { id: "attention", label: `Needs attention (${tasks.filter(attention).length})` },
              { id: "stable", label: `Stable (${tasks.filter((task) => !attention(task)).length})` },
            ] as const).map((option) => (
              <button
                key={option.id}
                type="button"
                aria-pressed={filter === option.id}
                onClick={() => setFilter(option.id)}
                className={`inline-flex min-h-11 items-center gap-1.5 rounded-xl border px-3 text-xs ${
                  filter === option.id ? "border-brand/40 bg-surfaceRaised text-ink" : "border-line bg-surface text-ink-secondary"
                }`}
              >
                <Filter aria-hidden="true" className="h-3.5 w-3.5" />
                {option.label}
              </button>
            ))}
          </div>
        </div>
        {visible.length === 0 ? (
          <p className="rounded-xl border border-line bg-surface p-4 text-sm text-ink-secondary">No task matches this filter.</p>
        ) : (
          <ul className="divide-y rounded-2xl border border-line bg-surface">
            {visible.map((task) => {
              const score = task.accuracy === null ? null : Math.floor(task.accuracy * 100);
              return (
                <li key={`${task.class_key}-${task.action}`} className="space-y-1 p-4">
                  <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <p className="break-words text-sm font-medium">
                      {(task.title || task.class_key) + " · " + (task.action_label || task.action.replace(/_/g, " ").toLowerCase())}
                    </p>
                    <p className="text-sm">
                      {score !== null ? (
                        <span className={attention(task) ? "text-status-warning" : "text-status-success"}>{score}% agreement</span>
                      ) : (
                        <span className="text-ink-tertiary">Not enough history yet</span>
                      )}
                    </p>
                  </div>
                  <p className="text-xs text-ink-tertiary">
                    Same {task.same} · Different {task.different} · Would have asked {task.would_ask} · No answer yet {task.censored}
                  </p>
                </li>
              );
            })}
          </ul>
        )}
      </section>
    </div>
  );
}

export function MetricsPanel({ metrics }: { metrics: MetricsSummaryResponse | null }) {
  if (metrics === null) {
    return (
      <StatePanel
        state="empty"
        title="Metrics are unavailable"
        description="Probation has not recorded enough activity to report counts for this account."
      />
    );
  }
  return (
    <div className="space-y-4">
      <dl className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {[
          { label: "Total proposals", value: metrics.proposals_total },
          { label: "Needs your decision", value: metrics.asks },
          { label: "Suggested for you", value: metrics.suggestions },
          { label: "Suggested to act", value: metrics.intended_actions },
          { label: "Confirmed effects", value: metrics.confirmed_effects },
          { label: "Result not confirmed", value: metrics.unconfirmed_effects },
        ].map((entry) => (
          <div key={entry.label} className="rounded-2xl border border-line bg-surface p-4">
            <dt className="text-xs text-ink-tertiary">{entry.label}</dt>
            <dd className="mt-1 text-2xl">{entry.value}</dd>
          </div>
        ))}
      </dl>
      {metrics.alarms.length > 0 && (
        <section aria-labelledby="alarms-title" className="space-y-2">
          <h2 id="alarms-title" className="text-base font-medium">
            Your habits changed
          </h2>
          <ul className="divide-y rounded-2xl border border-line bg-surface text-sm">
            {metrics.alarms.map((alarm) => (
              <li key={`${alarm.seq}-${alarm.created_at}`} className="p-3">
                {alarm.kind.replace(/_/g, " ")} · {alarm.created_at}
              </li>
            ))}
          </ul>
        </section>
      )}
      <section aria-labelledby="weeks-title" className="space-y-2">
        <h2 id="weeks-title" className="text-base font-medium">
          Weekly counts
        </h2>
        {metrics.weekly_series.length === 0 ? (
          <p className="rounded-xl border border-line bg-surface p-4 text-sm text-ink-secondary">No weeks recorded yet.</p>
        ) : (
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr className="border-b border-line text-left text-xs text-ink-secondary">
                <th scope="col" className="p-2">Week</th>
                <th scope="col" className="p-2">Needs you</th>
                <th scope="col" className="p-2">Suggested</th>
                <th scope="col" className="p-2">Acted on</th>
              </tr>
            </thead>
            <tbody>
              {metrics.weekly_series.map((week) => (
                <tr key={week.week} className="border-b border-line">
                  <th scope="row" className="p-2 font-normal">{week.week}</th>
                  <td className="p-2">{week.asks}</td>
                  <td className="p-2">{week.suggestions}</td>
                  <td className="p-2">{week.intended_actions}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}

interface HabitsPanelProps {
  habits: HabitItem[];
  busyId: string | null;
  error: string | null;
  onDeny(habitId: string): void;
}

export function HabitsPanel({ habits, busyId, error, onDeny }: HabitsPanelProps) {
  if (habits.length === 0) {
    return (
      <StatePanel
        state="empty"
        title="No learned patterns yet"
        description="Probation has not found a repeated pattern in this account's history."
      />
    );
  }
  return (
    <div className="space-y-3">
      <p className="text-sm text-ink-secondary">
        These sentences describe what Probation noticed. Dismissing one hides it; it does not change what Probation
        predicts, and it never grants or removes a permission.
      </p>
      {error !== null && <p role="alert" className="text-sm text-status-danger">{error}</p>}
      <ul className="space-y-2">
        {habits.map((habit) => (
          <li key={habit.id} className="flex flex-wrap items-start justify-between gap-3 rounded-2xl border border-line bg-surface p-4">
            <div className="min-w-0 space-y-1">
              <p className="break-words text-sm">{habit.statement}</p>
              <p className="text-xs text-ink-tertiary">
                Seen {habit.k} of {habit.n} times · {habit.clue}: {habit.clue_value}
              </p>
              {habit.denied && <p className="text-xs text-status-danger">Dismissed</p>}
            </div>
            {!habit.denied && (
              <Button variant="secondary" size="md" disabled={busyId !== null} onClick={() => onDeny(habit.id)}>
                {busyId === habit.id ? "Sending…" : "That is not right"}
              </Button>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

export function ChainsPanel({ chains }: { chains: ChainItem[] }) {
  if (chains.length === 0) {
    return (
      <StatePanel
        state="empty"
        title="No follow-on patterns yet"
        description="Probation has not found a repeated sequence of actions in this account's history."
      />
    );
  }
  return (
    <ul className="space-y-2">
      {chains.map((chain) => (
        <li key={chain.id} className="rounded-2xl border border-line bg-surface p-4 text-sm">
          <p className="flex flex-wrap items-center gap-2">
            <span className="break-words">{chain.trigger_class_key}</span>
            <ArrowRight aria-hidden="true" className="h-4 w-4 text-ink-tertiary" />
            <span className="font-medium">{chain.follow_action.replace(/_/g, " ").toLowerCase()}</span>
          </p>
          <p className="mt-1 text-xs text-ink-tertiary">
            Seen {chain.k} of {chain.n} times · each step needs its own permission
          </p>
        </li>
      ))}
    </ul>
  );
}

interface ExamsPanelProps {
  exams: ExamRunItem[];
  busy: boolean;
  error: string | null;
  onRun(classKey: string, action: string): void;
}

export function ExamsPanel({ exams, busy, error, onRun }: ExamsPanelProps) {
  const target = exams[0];
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-base font-medium">Trick-question tests</h2>
          <p className="text-sm text-ink-secondary">A test asks whether Probation would still decide the same way when the details change.</p>
        </div>
        <Button variant="secondary" size="md" disabled={busy || target === undefined} onClick={() => target && onRun(target.class_key, target.action)}>
          {busy ? "Queued…" : "Run a test"}
        </Button>
      </div>
      {error !== null && <p role="alert" className="text-sm text-status-danger">{error}</p>}
      {target === undefined ? (
        <StatePanel state="empty" title="No tests recorded" description="Probation has not run a test on this account's history yet." />
      ) : (
        <ul className="space-y-2">
          {exams.map((exam) => (
            <li key={exam.id} className="rounded-2xl border border-line bg-surface p-4 text-sm">
              <p className="break-words">
                {exam.class_key} · {exam.action.replace(/_/g, " ").toLowerCase()} · level {exam.level_tested}
              </p>
              <p className="mt-1 text-xs text-ink-tertiary">
                {exam.n_cases} cases ·{" "}
                {exam.passed === null
                  ? "Result not confirmed"
                  : exam.passed
                    ? "Passed"
                    : `Not passed (${exam.critical_violations ?? 0} critical)`}
                {" · "}
                {exam.finished_at ? `Finished ${exam.finished_at}` : "In progress"}
              </p>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
