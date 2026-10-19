import { useEffect, useState } from "react";
import {
  BarChart3,
  DollarSign,
  ShieldCheck,
  Sliders,
  CheckCircle2,
  RefreshCw,
  Lock,
  Radio,
  Sparkles,
  FileCheck,
} from "lucide-react";
import { apiClient } from "../api/client";
import {
  ExposureResponse,
  LedgerVerifyResponse,
  SettingsResponse,
  ReportCardResponse,
  MetricsSummaryResponse,
  HabitItem,
  ChainItem,
  ExamRunItem,
} from "../api/types";
import { Button } from "../components/common/Button";
import { ErrorBanner } from "../components/common/ErrorBanner";
import { InsightsView } from "./InsightsView";
import { RadarView } from "./RadarView";

export type CustomerMoreTab = "insights" | "usage" | "security" | "settings" | "radar";

interface MoreViewProps {
  reportCard: ReportCardResponse | null;
  metrics: MetricsSummaryResponse | null;
  habits: HabitItem[];
  chains: ChainItem[];
  exams: ExamRunItem[];
  onDenyHabit: (habitId: string) => Promise<void>;
  onRunExam: (classKey: string, action: string) => Promise<void>;
  radarActive?: boolean;
}

export const MoreView: React.FC<MoreViewProps> = ({
  reportCard,
  metrics,
  habits,
  chains,
  exams,
  onDenyHabit,
  onRunExam,
  radarActive = false,
}) => {
  const [activeTab, setActiveTab] = useState<CustomerMoreTab>("insights");
  const [exposure, setExposure] = useState<ExposureResponse | null>(null);
  const [ledger, setLedger] = useState<LedgerVerifyResponse | null>(null);
  const [settings, setSettings] = useState<SettingsResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchTabDetails = async () => {
    if (activeTab === "insights" || activeTab === "radar") return;

    setLoading(true);
    setError(null);
    try {
      if (activeTab === "usage") {
        const data = await apiClient.getExposure();
        setExposure(data);
      } else if (activeTab === "security") {
        const data = await apiClient.verifyLedger();
        setLedger(data);
      } else if (activeTab === "settings") {
        const data = await apiClient.getSettings();
        setSettings(data);
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load details");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchTabDetails();
  }, [activeTab]);

  const tabs: Array<{ id: CustomerMoreTab; label: string; icon: React.ElementType }> = [
    { id: "insights", label: "Performance & Trust", icon: BarChart3 },
    { id: "usage", label: "Cost & Usage", icon: DollarSign },
    { id: "security", label: "Security & Audit Log", icon: ShieldCheck },
    { id: "settings", label: "Preferences & Safety", icon: Sliders },
    ...(radarActive ? [{ id: "radar" as CustomerMoreTab, label: "Radar Opportunities", icon: Radio }] : []),
  ];

  return (
    <div className="space-y-6">
      {/* Editorial Header */}
      <div>
        <h1 className="font-serif text-3xl sm:text-4xl font-normal text-ink tracking-tight">
          Account & Insights
        </h1>
        <p className="text-sm text-ink-secondary mt-1">
          Monitor your AI's accuracy, track monthly usage and spending, and adjust safety preferences.
        </p>
      </div>

      {/* Customer-First Navigation Tabs */}
      <div className="flex items-center gap-2 border-b border-line pb-3 overflow-x-auto">
        {tabs.map((tab) => {
          const Icon = tab.icon;
          const isActive = activeTab === tab.id;
          return (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-semibold whitespace-nowrap transition-all ${
                isActive
                  ? "bg-surfaceRaised text-brand border border-brand/40 shadow-sm"
                  : "text-ink-secondary hover:text-ink hover:bg-surfaceSubtle border border-transparent"
              }`}
            >
              <Icon className={`w-4 h-4 ${isActive ? "text-brand" : "text-ink-tertiary"}`} />
              <span>{tab.label}</span>
            </button>
          );
        })}
      </div>

      {error && <ErrorBanner message={error} onRetry={fetchTabDetails} />}

      {/* 1. PERFORMANCE & TRUST (Report Card, Habits, Safety Tests) */}
      {activeTab === "insights" && (
        <InsightsView
          reportCard={reportCard}
          metrics={metrics}
          habits={habits}
          chains={chains}
          exams={exams}
          onDenyHabit={onDenyHabit}
          onRunExam={onRunExam}
        />
      )}

      {/* 2. COST & USAGE (Plain English, Clear Spending Limits) */}
      {activeTab === "usage" && (
        <div className="space-y-6">
          <div className="p-6 rounded-2xl bg-surface border border-line space-y-2 shadow-sm">
            <div className="flex items-center gap-2 text-xs font-semibold text-brand uppercase tracking-wider">
              <DollarSign className="w-4 h-4" />
              <span>Usage & AI Spending</span>
            </div>
            <h2 className="font-serif text-2xl font-bold text-ink">
              Transparent AI Cost Tracking
            </h2>
            <p className="text-xs sm:text-sm text-ink-secondary leading-relaxed max-w-2xl">
              Probation uses foundation models on your behalf only when required. Your spending is protected
              by an automatic hard ceiling so you never receive unexpected charges.
            </p>
          </div>

          {loading ? (
            <div className="h-44 bg-surface rounded-2xl border border-line animate-pulse" />
          ) : exposure ? (
            <div className="space-y-5">
              {/* 3 Metric Cards */}
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                <div className="p-5 rounded-2xl bg-surface border border-line">
                  <span className="text-xs text-ink-tertiary uppercase tracking-wider font-semibold">
                    Current Monthly Spend
                  </span>
                  <div className="text-3xl font-bold text-brand mt-1.5">
                    ${exposure.total_cost_usd.toFixed(2)}
                  </div>
                  <div className="text-xs text-ink-secondary mt-1">Hard limit: $15.00 / month</div>
                </div>

                <div className="p-5 rounded-2xl bg-surface border border-line">
                  <span className="text-xs text-ink-tertiary uppercase tracking-wider font-semibold">
                    AI Tasks Handled
                  </span>
                  <div className="text-3xl font-bold text-ink mt-1.5">
                    {exposure.calls}
                  </div>
                  <div className="text-xs text-ink-secondary mt-1">Drafts and classifications</div>
                </div>

                <div className="p-5 rounded-2xl bg-surface border border-line">
                  <span className="text-xs text-[#85B99A] uppercase tracking-wider font-semibold">
                    Budget Protected
                  </span>
                  <div className="w-full bg-surfaceSubtle h-2.5 rounded-full overflow-hidden border border-line mt-3 mb-2">
                    <div
                      className="bg-brand h-full rounded-full transition-all"
                      style={{
                        width: `${Math.min(100, Math.max(3, (exposure.total_cost_usd / 15.0) * 100))}%`,
                      }}
                    />
                  </div>
                  <div className="flex justify-between text-[11px] text-ink-tertiary">
                    <span>${exposure.total_cost_usd.toFixed(2)} used</span>
                    <span>${(15.0 - exposure.total_cost_usd).toFixed(2)} remaining</span>
                  </div>
                </div>
              </div>

              {/* Breakdown by Activity Type */}
              <div className="p-6 rounded-2xl bg-surface border border-line space-y-4 shadow-sm">
                <h3 className="text-sm font-bold text-ink">Usage by Task Type</h3>

                <div className="divide-y divide-line">
                  {exposure.breakdown.map((row, idx) => (
                    <div key={idx} className="py-3 flex items-center justify-between text-xs">
                      <div>
                        <span className="font-semibold text-ink">
                          {row.call_kind.replace(/_/g, " ").toUpperCase()}
                        </span>
                        <div className="text-[11px] text-ink-tertiary mt-0.5">
                          {row.calls} tasks processed
                        </div>
                      </div>
                      <div className="text-right">
                        <span className="font-bold text-brand">${row.cost_usd.toFixed(4)}</span>
                        <div className="text-[11px] text-ink-tertiary">
                          {(row.tokens_in + row.tokens_out).toLocaleString()} tokens
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          ) : null}
        </div>
      )}

      {/* 3. SECURITY & AUDIT LOG (Privacy & Tamper Proof Guarantees) */}
      {activeTab === "security" && (
        <div className="space-y-6">
          <div className="p-6 rounded-2xl bg-surface border border-line space-y-2 shadow-sm">
            <div className="flex items-center gap-2 text-xs font-semibold text-[#85B99A] uppercase tracking-wider">
              <ShieldCheck className="w-4 h-4" />
              <span>Data Protection & Audit Trail</span>
            </div>
            <h2 className="font-serif text-2xl font-bold text-ink">
              Your Data Stays on Your Computer
            </h2>
            <p className="text-xs sm:text-sm text-ink-secondary leading-relaxed max-w-2xl">
              Probation runs local-first. Your emails, calendar events, and files are stored strictly on your
              local machine. Every action taken is cryptographically sealed in an append-only audit trail.
            </p>
          </div>

          {loading ? (
            <div className="h-44 bg-surface rounded-2xl border border-line animate-pulse" />
          ) : ledger ? (
            <div className="space-y-5">
              {/* Verification Hero Card */}
              <div className="p-6 rounded-2xl bg-surface border border-line flex flex-col sm:flex-row sm:items-center justify-between gap-4 shadow-sm">
                <div className="flex items-center gap-4">
                  <div className="w-12 h-12 rounded-2xl bg-[#85B99A]/15 text-[#85B99A] border border-[#85B99A]/30 flex items-center justify-center shrink-0">
                    <CheckCircle2 className="w-7 h-7" />
                  </div>
                  <div>
                    <h3 className="text-base font-bold text-ink">
                      Audit Trail 100% Cryptographically Verified
                    </h3>
                    <p className="text-xs text-ink-secondary mt-0.5">
                      All {ledger.length} past decisions, approvals, and actions have been verified against the tamper-evident hash chain.
                    </p>
                  </div>
                </div>

                <Button
                  variant="secondary"
                  size="sm"
                  onClick={fetchTabDetails}
                  className="font-medium text-xs border-line hover:border-brand/40 shrink-0"
                >
                  <RefreshCw className="w-3.5 h-3.5 mr-1.5" />
                  <span>Verify Now</span>
                </Button>
              </div>

              {/* 3 Privacy Guarantees */}
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                <div className="p-4 rounded-xl bg-surfaceRaised border border-line space-y-1.5">
                  <div className="flex items-center gap-2 text-xs font-bold text-ink">
                    <Lock className="w-4 h-4 text-brand" />
                    <span>Automatic PII Redaction</span>
                  </div>
                  <p className="text-xs text-ink-secondary leading-relaxed">
                    Personal names, emails, phone numbers, and credentials are automatically scrubbed before any AI prompt is processed.
                  </p>
                </div>

                <div className="p-4 rounded-xl bg-surfaceRaised border border-line space-y-1.5">
                  <div className="flex items-center gap-2 text-xs font-bold text-ink">
                    <FileCheck className="w-4 h-4 text-[#85B99A]" />
                    <span>Append-Only Record</span>
                  </div>
                  <p className="text-xs text-ink-secondary leading-relaxed">
                    Past history can never be rewritten or deleted. Every decision is recorded permanently in your local database.
                  </p>
                </div>

                <div className="p-4 rounded-xl bg-surfaceRaised border border-line space-y-1.5">
                  <div className="flex items-center gap-2 text-xs font-bold text-ink">
                    <Sparkles className="w-4 h-4 text-[#C8B27D]" />
                    <span>Fail-Closed Safety</span>
                  </div>
                  <p className="text-xs text-ink-secondary leading-relaxed">
                    If an unexpected error or uncertainty occurs, Probation always pauses and asks you rather than guessing.
                  </p>
                </div>
              </div>

              {/* Technical Hash Identifier (Subtle) */}
              <div className="p-4 rounded-xl bg-[#131F1C] border border-[#344840]/60 flex items-center justify-between text-xs text-ink-tertiary font-mono">
                <span>Latest Ledger Seal:</span>
                <span className="text-brand truncate max-w-sm ml-2">{ledger.head_hash}</span>
              </div>
            </div>
          ) : null}
        </div>
      )}

      {/* 4. PREFERENCES & SAFETY (Customer-friendly settings) */}
      {activeTab === "settings" && (
        <div className="space-y-6">
          <div className="p-6 rounded-2xl bg-surface border border-line space-y-2 shadow-sm">
            <div className="flex items-center gap-2 text-xs font-semibold text-brand uppercase tracking-wider">
              <Sliders className="w-4 h-4" />
              <span>Safety Controls & Preferences</span>
            </div>
            <h2 className="font-serif text-2xl font-bold text-ink">
              How Probation Protects Your Routine
            </h2>
            <p className="text-xs sm:text-sm text-ink-secondary leading-relaxed max-w-2xl">
              These hard-coded safety guardrails ensure your AI only acts when statistical confidence is proven.
            </p>
          </div>

          {loading ? (
            <div className="h-44 bg-surface rounded-2xl border border-line animate-pulse" />
          ) : settings ? (
            <div className="space-y-4">
              <div className="p-5 rounded-2xl bg-surface border border-line space-y-4 shadow-sm">
                <div className="flex items-center justify-between py-2 border-b border-line">
                  <div>
                    <h4 className="text-sm font-semibold text-ink">Random Spot-Check Rate</h4>
                    <p className="text-xs text-ink-secondary mt-0.5">
                      Fraction of routine actions held for manual human confirmation to ensure ongoing quality.
                    </p>
                  </div>
                  <span className="text-xs font-bold font-mono px-3 py-1 rounded-full bg-brand/10 text-brand">
                    {(settings.audit_fraction * 100).toFixed(0)}% Spot Check
                  </span>
                </div>

                <div className="flex items-center justify-between py-2 border-b border-line">
                  <div>
                    <h4 className="text-sm font-semibold text-ink">Monthly Spending Ceiling</h4>
                    <p className="text-xs text-ink-secondary mt-0.5">
                      Maximum allowable compute spending across all AI models per billing period.
                    </p>
                  </div>
                  <span className="text-xs font-bold font-mono px-3 py-1 rounded-full bg-surfaceSubtle border border-line text-ink">
                    ${settings.budget_hard_limit_usd.toFixed(2)} USD
                  </span>
                </div>

                <div className="flex items-center justify-between py-2 border-b border-line">
                  <div>
                    <h4 className="text-sm font-semibold text-ink">Confidence Level for Suggestions</h4>
                    <p className="text-xs text-ink-secondary mt-0.5">
                      Minimum required statistical agreement on your own past history before making suggestions.
                    </p>
                  </div>
                  <span className="text-xs font-bold font-mono px-3 py-1 rounded-full bg-[#85B99A]/15 text-[#85B99A]">
                    {Math.round(settings.l1_min_lb * 100)}% Safe Estimate
                  </span>
                </div>

                <div className="flex items-center justify-between py-2">
                  <div>
                    <h4 className="text-sm font-semibold text-ink">System Clock Mode</h4>
                    <p className="text-xs text-ink-secondary mt-0.5">
                      Clock source governing timestamps and temporal isolation.
                    </p>
                  </div>
                  <span className="text-xs font-bold font-mono px-3 py-1 rounded-full bg-surfaceSubtle border border-line text-ink capitalize">
                    {settings.clock_mode}
                  </span>
                </div>
              </div>
            </div>
          ) : null}
        </div>
      )}

      {/* 5. RADAR (Conditional) */}
      {activeTab === "radar" && <RadarView />}
    </div>
  );
};
