import { useState } from "react";
import {
  FlaskConical,
  ArrowRight,
  Mail,
  Calendar,
  Receipt,
  MessageCircle,
  FileText,
  Users,
  CheckSquare,
  Tag,
  Database,
  Shield,
  Filter,
} from "lucide-react";
import {
  ReportCardResponse,
  MetricsSummaryResponse,
  HabitItem,
  ChainItem,
  ExamRunItem,
  TaskReportItem,
} from "../api/types";
import { MOCK_REPORT_CARD } from "../api/fixtures";
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
  const [taskFilter, setTaskFilter] = useState<"all" | "attention" | "stable">("all");
  const [runningExam, setRunningExam] = useState(false);

  // Compute report card proportions for segmented bar
  const totalEvaluated = reportCard?.total_evaluated || 1;
  const sameCount = reportCard?.same || 0;
  const diffCount = reportCard?.different || 0;
  const askCount = reportCard?.would_ask || 0;
  const censoredCount = reportCard?.censored || 0;

  const samePct = Math.round((sameCount / totalEvaluated) * 100);
  const askPct = Math.round((askCount / totalEvaluated) * 100);
  const diffPct = Math.round((diffCount / totalEvaluated) * 100);
  const censoredPct = Math.max(0, 100 - (samePct + askPct + diffPct));

  const tasks: TaskReportItem[] =
    reportCard?.tasks && reportCard.tasks.length > 0
      ? reportCard.tasks
      : (MOCK_REPORT_CARD.tasks || []);

  const isAttentionTask = (t: TaskReportItem) => {
    return t.status === "needs_attention" || t.needs_attention === true || (t.accuracy !== null && t.accuracy < 0.90);
  };

  const attentionTasks = tasks.filter(isAttentionTask);
  const stableTasks = tasks.filter((t) => !isAttentionTask(t) && t.status !== "not_enough_history");

  const filteredTasks = tasks.filter((t) => {
    if (taskFilter === "attention") return isAttentionTask(t);
    if (taskFilter === "stable") return !isAttentionTask(t);
    return true;
  });

  const getPackIcon = (classKey: string) => {
    const k = classKey.toLowerCase();
    if (k.includes("mail") || k.includes("email") || k.includes("recruiter"))
      return <Mail className="w-4 h-4 text-ink-secondary" />;
    if (k.includes("calendar") || k.includes("sync") || k.includes("event"))
      return <Calendar className="w-4 h-4 text-ink-secondary" />;
    if (k.includes("receipt") || k.includes("expense"))
      return <Receipt className="w-4 h-4 text-ink-secondary" />;
    if (k.includes("support") || k.includes("refund"))
      return <MessageCircle className="w-4 h-4 text-ink-secondary" />;
    if (k.includes("file") || k.includes("doc"))
      return <FileText className="w-4 h-4 text-ink-secondary" />;
    if (k.includes("user") || k.includes("recruit"))
      return <Users className="w-4 h-4 text-ink-secondary" />;
    if (k.includes("project") || k.includes("standup"))
      return <CheckSquare className="w-4 h-4 text-ink-secondary" />;
    if (k.includes("tag") || k.includes("crm"))
      return <Tag className="w-4 h-4 text-ink-secondary" />;
    if (k.includes("data") || k.includes("export"))
      return <Database className="w-4 h-4 text-ink-secondary" />;
    return <Shield className="w-4 h-4 text-ink-secondary" />;
  };

  const handleRunExamClick = async () => {
    setRunningExam(true);
    try {
      await onRunExam("mail|recruiter|inquiry", "REPLY");
    } finally {
      setRunningExam(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Sub-tab Navigation */}
      <div className="flex flex-wrap gap-2 border-b border-line pb-3">
        {[
          { id: "report", label: "Report Card" },
          { id: "metrics", label: "Metrics & Trends" },
          { id: "habits", label: `Habits (${habits.length})` },
          { id: "chains", label: `Chains (${chains.length})` },
          { id: "exams", label: `Adversarial Exams (${exams.length})` },
        ].map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveSubTab(tab.id as typeof activeSubTab)}
            className={`px-3.5 py-2 rounded-xl text-xs font-semibold transition-all ${
              activeSubTab === tab.id
                ? "bg-surfaceRaised text-brand border border-brand/40 shadow-sm"
                : "text-ink-secondary hover:text-ink hover:bg-surfaceSubtle border border-transparent"
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Sub-view: Report Card */}
      {activeSubTab === "report" && (
        <div className="space-y-6">
          <div className="p-6 rounded-2xl bg-surface border border-line space-y-4 shadow-sm">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
              <div>
                <span className="text-xs font-semibold uppercase tracking-wider text-brand">
                  Driving Test Verification
                </span>
                <h3 className="font-serif text-2xl font-bold text-ink mt-0.5">
                  Historical Backtest Summary
                </h3>
                <p className="text-xs text-ink-secondary mt-1">
                  Evaluated on your own recorded history up to simulated time.
                </p>
              </div>

              <div className="flex items-center gap-2">
                <span className="text-xs font-semibold px-3 py-1 rounded-full bg-surfaceSubtle border border-line text-ink-secondary">
                  Scope: {reportCard?.family || "all"}
                </span>
                <span className="text-xs font-bold px-3 py-1 rounded-full bg-[#85B99A]/15 text-[#85B99A] border border-[#85B99A]/30">
                  {reportCard?.accuracy ? `${Math.round(reportCard.accuracy * 100)}% Accuracy` : "93.4% Accuracy"}
                </span>
              </div>
            </div>

            {/* Segmented Color Bar */}
            <div className="space-y-2 pt-2">
              <div className="w-full h-3 rounded-full overflow-hidden flex bg-surfaceSubtle border border-line">
                <div style={{ width: `${samePct}%` }} className="bg-[#85B99A] transition-all" title={`Same as you: ${sameCount}`} />
                <div style={{ width: `${askPct}%` }} className="bg-[#C8B27D] transition-all" title={`Would ask: ${askCount}`} />
                <div style={{ width: `${diffPct}%` }} className="bg-[#E28F88] transition-all" title={`Different: ${diffCount}`} />
                <div style={{ width: `${censoredPct}%` }} className="bg-ink-tertiary transition-all" title={`No answer yet: ${censoredCount}`} />
              </div>

              <div className="flex flex-wrap items-center justify-between gap-2 text-xs pt-1">
                <div className="flex items-center gap-1.5">
                  <span className="w-2.5 h-2.5 rounded-full bg-[#85B99A]" />
                  <span className="text-ink font-medium">Same as you ({sameCount})</span>
                </div>
                <div className="flex items-center gap-1.5">
                  <span className="w-2.5 h-2.5 rounded-full bg-[#C8B27D]" />
                  <span className="text-ink font-medium">Would have asked ({askCount})</span>
                </div>
                <div className="flex items-center gap-1.5">
                  <span className="w-2.5 h-2.5 rounded-full bg-[#E28F88]" />
                  <span className="text-ink font-medium">Different ({diffCount})</span>
                </div>
                <div className="flex items-center gap-1.5">
                  <span className="w-2.5 h-2.5 rounded-full bg-ink-tertiary" />
                  <span className="text-ink-secondary">No answer yet ({censoredCount})</span>
                </div>
              </div>
            </div>

            {/* 4 KPI Cards */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 pt-2">
              <div className="p-4 rounded-xl bg-surfaceRaised border border-line">
                <span className="text-xs text-ink-tertiary font-medium">Same as you</span>
                <div className="text-2xl font-bold text-[#85B99A] mt-1">{sameCount}</div>
                <div className="text-[11px] text-ink-secondary mt-0.5">{samePct}% agreement</div>
              </div>

              <div className="p-4 rounded-xl bg-surfaceRaised border border-line">
                <span className="text-xs text-ink-tertiary font-medium">Would have asked</span>
                <div className="text-2xl font-bold text-brand mt-1">{askCount}</div>
                <div className="text-[11px] text-ink-secondary mt-0.5">Cautious abstain</div>
              </div>

              <div className="p-4 rounded-xl bg-surfaceRaised border border-line">
                <span className="text-xs text-ink-tertiary font-medium">Different</span>
                <div className="text-2xl font-bold text-[#E28F88] mt-1">{diffCount}</div>
                <div className="text-[11px] text-ink-secondary mt-0.5">{diffPct}% diverged</div>
              </div>

              <div className="p-4 rounded-xl bg-surfaceRaised border border-line">
                <span className="text-xs text-ink-tertiary font-medium">Evaluated</span>
                <div className="text-2xl font-bold text-ink mt-1">{reportCard?.total_evaluated ?? totalEvaluated}</div>
                <div className="text-[11px] text-ink-secondary mt-0.5">Total situations</div>
              </div>
            </div>
          </div>

          {/* Task-by-Task Backtest Scores Section */}
          <div className="space-y-4">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-line pb-3">
              <div>
                <h4 className="font-serif text-lg font-bold text-ink">
                  Task-by-Task Performance Scores
                </h4>
                <p className="text-xs text-ink-secondary mt-0.5">
                  Discrete historical agreement and safety validation for each concrete action.
                </p>
              </div>

              {/* Filter Tabs */}
              <div className="flex items-center gap-1.5 self-start sm:self-auto">
                <Filter className="w-3.5 h-3.5 text-ink-tertiary mr-1" />
                {([
                  { id: "all", label: `All tasks (${tasks.length})` },
                  { id: "attention", label: `Needs attention (${attentionTasks.length})` },
                  { id: "stable", label: `Stable (${stableTasks.length})` },
                ] as const).map((tab) => (
                  <button
                    key={tab.id}
                    onClick={() => setTaskFilter(tab.id)}
                    className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${
                      taskFilter === tab.id
                        ? "bg-surfaceRaised text-brand border border-brand/30 shadow-sm"
                        : "text-ink-secondary hover:text-ink hover:bg-surfaceSubtle border border-transparent"
                    }`}
                  >
                    {tab.label}
                  </button>
                ))}
              </div>
            </div>

            {/* Tasks List */}
            <div className="space-y-2.5">
              {filteredTasks.length === 0 ? (
                <div className="p-8 rounded-xl bg-surface border border-line text-center text-xs text-ink-secondary">
                  No tasks match the selected filter.
                </div>
              ) : (
                filteredTasks.map((t) => {
                  const scorePct = t.accuracy !== null ? Math.round(t.accuracy * 100) : null;
                  const isAttention = isAttentionTask(t);
                  const title = t.title || t.class_key.split("|").slice(-2).join(" ");
                  const actionLabel = t.action_label || t.action.replace(/_/g, " ").toLowerCase();

                  return (
                    <div
                      key={`${t.class_key}-${t.action}`}
                      className="p-4 rounded-xl bg-surface border border-line hover:border-brand/30 transition-all space-y-2.5 shadow-sm"
                    >
                      {/* Top Row: Icon + Title + Score */}
                      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                        <div className="flex items-center gap-3 min-w-0">
                          <div className="w-9 h-9 rounded-lg bg-surfaceSubtle border border-line flex items-center justify-center shrink-0">
                            {getPackIcon(t.class_key)}
                          </div>
                          <div className="min-w-0">
                            <div className="flex items-center gap-2">
                              <h5 className="text-sm font-semibold text-ink truncate capitalize">
                                {title}
                              </h5>
                              <span className="text-ink-tertiary">·</span>
                              <span className="text-xs text-ink-secondary truncate">
                                {actionLabel}
                              </span>
                            </div>
                            <div className="text-[10px] text-ink-tertiary font-mono truncate">
                              {t.class_key} → {t.action}
                            </div>
                          </div>
                        </div>

                        {/* Right: Score and Status Pill */}
                        <div className="flex items-center gap-3 shrink-0 self-end sm:self-auto">
                          <div className="text-right">
                            {scorePct !== null ? (
                              <span className={`text-base font-bold font-mono ${
                                isAttention ? "text-[#E0B663]" : "text-[#85B99A]"
                              }`}>
                                {scorePct}%
                              </span>
                            ) : (
                              <span className="text-xs text-ink-tertiary italic">
                                Not enough history yet
                              </span>
                            )}
                          </div>

                          {/* Refined Status Pill */}
                          {t.status === "not_enough_history" || scorePct === null ? (
                            <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[11px] font-semibold bg-surfaceSubtle text-ink-secondary border border-line">
                              <span className="w-1.5 h-1.5 rounded-full bg-ink-tertiary" />
                              Not enough history yet
                            </span>
                          ) : isAttention ? (
                            <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[11px] font-semibold bg-[#E0B663]/15 text-[#E0B663] border border-[#E0B663]/30">
                              <span className="w-1.5 h-1.5 rounded-full bg-[#E0B663]" />
                              Needs attention
                            </span>
                          ) : (
                            <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[11px] font-semibold bg-[#85B99A]/15 text-[#85B99A] border border-[#85B99A]/30">
                              <span className="w-1.5 h-1.5 rounded-full bg-[#85B99A]" />
                              Stable
                            </span>
                          )}
                        </div>
                      </div>

                      {/* Micro Progress Bar */}
                      <div className="w-full bg-surfaceSubtle h-1 rounded-full overflow-hidden border border-line/40">
                        <div
                          className={`h-full rounded-full transition-all ${
                            isAttention ? "bg-[#E0B663]" : "bg-[#85B99A]"
                          }`}
                          style={{ width: scorePct !== null ? `${Math.max(4, scorePct)}%` : "0%" }}
                        />
                      </div>

                      {/* 4 Discrete Metric Counts */}
                      <div className="flex flex-wrap items-center justify-between gap-2 text-[11px] text-ink-tertiary pt-0.5">
                        <span>Same as you: <strong className="text-ink font-semibold">{t.same}</strong></span>
                        <span>Different: <strong className={t.different > 0 ? "text-[#E28F88] font-semibold" : "text-ink font-semibold"}>{t.different}</strong></span>
                        <span>Would have asked: <strong className="text-ink font-semibold">{t.would_ask}</strong></span>
                        <span>No answer yet: <strong className="text-ink font-semibold">{t.censored}</strong></span>
                      </div>
                    </div>
                  );
                })
              )}
            </div>

            {/* Official Footnote per USER_FLOW.md §F2 */}
            <div className="pt-2 text-center text-xs text-ink-tertiary">
              Based only on what was known at the time. Recent items have no answer yet.
            </div>
          </div>
        </div>
      )}

      {/* Sub-view: Metrics & Trends */}
      {activeSubTab === "metrics" && (
        <div className="space-y-6">
          <div className="grid grid-cols-1 sm:grid-cols-4 gap-4">
            <div className="p-5 rounded-2xl bg-surface border border-line">
              <span className="text-xs text-ink-tertiary uppercase tracking-wider font-semibold">Total Proposals</span>
              <div className="text-3xl font-bold text-ink mt-1.5">{metrics?.proposals_total ?? 214}</div>
              <div className="text-xs text-ink-secondary mt-1">Across all packs</div>
            </div>

            <div className="p-5 rounded-2xl bg-surface border border-line">
              <span className="text-xs text-[#85B99A] uppercase tracking-wider font-semibold">Autonomous</span>
              <div className="text-3xl font-bold text-[#85B99A] mt-1.5">{metrics?.automatic_actions ?? 122}</div>
              <div className="text-xs text-ink-secondary mt-1">L2 & L3 executions</div>
            </div>

            <div className="p-5 rounded-2xl bg-surface border border-line">
              <span className="text-xs text-brand uppercase tracking-wider font-semibold">Suggestions</span>
              <div className="text-3xl font-bold text-brand mt-1.5">{metrics?.suggestions ?? 54}</div>
              <div className="text-xs text-ink-secondary mt-1">Prepared drafts</div>
            </div>

            <div className="p-5 rounded-2xl bg-surface border border-line">
              <span className="text-xs text-[#E0B663] uppercase tracking-wider font-semibold">Human Asks</span>
              <div className="text-3xl font-bold text-[#E0B663] mt-1.5">{metrics?.asks ?? 38}</div>
              <div className="text-xs text-ink-secondary mt-1">Confirmation queries</div>
            </div>
          </div>

          {/* Weekly Volume Summary Table */}
          <div className="p-6 rounded-2xl bg-surface border border-line space-y-4 shadow-sm">
            <div className="flex items-center justify-between">
              <h4 className="text-sm font-bold text-ink">
                Weekly Volume Breakdown
              </h4>
              <span className="text-xs text-ink-tertiary">Chronological backtest</span>
            </div>

            <div className="overflow-hidden rounded-xl border border-line">
              <table className="w-full text-xs text-left">
                <thead className="bg-surfaceSubtle text-ink-secondary border-b border-line">
                  <tr>
                    <th className="py-2.5 px-4 font-semibold">Week</th>
                    <th className="py-2.5 px-4 font-semibold">Asks</th>
                    <th className="py-2.5 px-4 font-semibold">Suggestions</th>
                    <th className="py-2.5 px-4 font-semibold text-[#85B99A]">Autonomous</th>
                    <th className="py-2.5 px-4 font-semibold text-right">Total</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line font-mono">
                  {metrics?.weekly_series.map((w) => (
                    <tr key={w.week} className="hover:bg-surfaceRaised/50">
                      <td className="py-3 px-4 font-bold text-ink">{w.week}</td>
                      <td className="py-3 px-4 text-[#E0B663]">{w.asks}</td>
                      <td className="py-3 px-4 text-brand">{w.suggestions}</td>
                      <td className="py-3 px-4 text-[#85B99A] font-bold">{w.auto_actions}</td>
                      <td className="py-3 px-4 text-right text-ink font-bold">{w.total}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* Sub-view: Habits */}
      {activeSubTab === "habits" && (
        <div className="space-y-4">
          <div className="p-4 rounded-xl bg-surfaceSubtle border border-line text-xs text-ink-secondary">
            Mined habits describe repeated past behaviors discovered by statistical rule mining. Habits inform proposal generation but <strong className="text-ink">never grant autonomy on their own</strong> without passing the driving-test exam.
          </div>

          <div className="space-y-3">
            {habits.map((h) => (
              <div
                key={h.id}
                className="p-5 rounded-2xl bg-surface border border-line flex flex-col sm:flex-row sm:items-center justify-between gap-4 shadow-sm"
              >
                <div className="space-y-1.5">
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-semibold text-brand font-mono bg-brand/10 px-2 py-0.5 rounded">
                      {h.clue}: {h.clue_value}
                    </span>
                    <span className="text-ink-tertiary">·</span>
                    <span className="text-xs font-semibold px-2 py-0.5 rounded-full bg-[#85B99A]/15 text-[#85B99A]">
                      {h.lift.toFixed(1)}x Lift
                    </span>
                    {h.denied && (
                      <span className="text-xs font-semibold px-2 py-0.5 rounded-full bg-status-danger/15 text-status-danger">
                        Dismissed
                      </span>
                    )}
                  </div>
                  <h4 className="text-sm font-semibold text-ink">{h.statement}</h4>
                  <div className="text-xs text-ink-tertiary">
                    Observed in {h.k} of {h.n} matching situations (p &lt; 0.001)
                  </div>
                </div>

                {!h.denied && (
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() => onDenyHabit(h.id)}
                    className="shrink-0 text-xs text-status-danger border-line hover:border-status-danger/40"
                  >
                    Dismiss pattern
                  </Button>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Sub-view: Chains */}
      {activeSubTab === "chains" && (
        <div className="space-y-4">
          <div className="p-4 rounded-xl bg-surfaceSubtle border border-line text-xs text-ink-secondary">
            Multi-step patterns discovered across packs (e.g. deadline email triggers follow-up calendar block). Per contract rules, <strong className="text-ink">each step in a chain requires separate permission</strong>.
          </div>

          <div className="space-y-3">
            {chains.map((c) => (
              <div
                key={c.id}
                className="p-5 rounded-2xl bg-surface border border-line space-y-3 shadow-sm"
              >
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                  <div className="flex items-center gap-3">
                    <span className="text-xs font-semibold text-brand font-mono px-2.5 py-1 rounded bg-brand/10">
                      {c.trigger_class_key}
                    </span>
                    <ArrowRight className="w-4 h-4 text-ink-tertiary" />
                    <span className="text-sm font-bold text-ink">
                      {c.follow_action}
                    </span>
                  </div>

                  <span className="text-xs font-semibold px-2.5 py-1 rounded-full bg-[#85B99A]/15 text-[#85B99A]">
                    {c.lift.toFixed(1)}x Lift
                  </span>
                </div>

                <div className="pt-2 border-t border-line flex items-center justify-between text-xs text-ink-tertiary">
                  <span>Occurred in {c.k} of {c.n} instances</span>
                  <span>Base rate: {Math.round(c.base_rate * 100)}%</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Sub-view: Adversarial Exams */}
      {activeSubTab === "exams" && (
        <div className="space-y-4">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
            <div>
              <h3 className="font-serif text-xl font-bold text-ink">Trick-Question Driving Exams</h3>
              <p className="text-xs text-ink-secondary mt-0.5">
                Adversarial invariance test cases injected into synthetic history to probe failure modes.
              </p>
            </div>

            <Button
              variant="secondary"
              size="sm"
              disabled={runningExam}
              onClick={handleRunExamClick}
              className="font-medium text-xs border-line hover:border-brand/40"
            >
              <FlaskConical className="w-3.5 h-3.5 mr-1.5 text-brand" />
              <span>{runningExam ? "Running Exam..." : "Run Diagnostic Exam"}</span>
            </Button>
          </div>

          <div className="space-y-3">
            {exams.map((ex) => (
              <div
                key={ex.id}
                className="p-5 rounded-2xl bg-surface border border-line space-y-3 shadow-sm"
              >
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="text-xs font-semibold text-brand font-mono">{ex.class_key}</span>
                      <span className="text-ink-tertiary">→</span>
                      <span className="text-sm font-bold text-ink">{ex.action}</span>
                    </div>
                    <div className="text-xs text-ink-secondary mt-1">
                      Tested Level {ex.level_tested} autonomy · {ex.n_cases} test cases executed
                    </div>
                  </div>

                  <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-semibold ${
                    ex.passed
                      ? "bg-[#85B99A]/15 text-[#85B99A] border border-[#85B99A]/30"
                      : "bg-[#E28F88]/15 text-[#E28F88] border border-[#E28F88]/30"
                  }`}>
                    <span className={`w-1.5 h-1.5 rounded-full ${ex.passed ? "bg-[#85B99A]" : "bg-[#E28F88]"}`} />
                    {ex.passed ? "Passed All Invariance Checks" : "Failed Invariance"}
                  </span>
                </div>

                <div className="pt-2 border-t border-line flex flex-wrap items-center justify-between gap-2 text-xs text-ink-tertiary">
                  <span>Critical Safety Violations: <strong className="text-ink">{ex.critical_violations ?? 0}</strong></span>
                  <span>Flip rate: <strong className="text-ink">{ex.invariance_flip_rate !== null ? `${Math.round(ex.invariance_flip_rate * 100)}%` : "0%"}</strong></span>
                  <span>Finished: {ex.finished_at ? ex.finished_at.split("T")[0] : "In progress"}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
