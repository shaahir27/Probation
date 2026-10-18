import { useEffect, useState } from "react";
import {
  ShieldCheck,
  Eye,
  Globe,
  Sliders,
  Play,
  Pause,
  Radio,
  CheckCircle2,
  AlertTriangle,
  ExternalLink,
  RefreshCw,
  Lock,
  BarChart3,
} from "lucide-react";
import { apiClient } from "../api/client";
import {
  ExposureResponse,
  WebFactsResponse,
  LedgerVerifyResponse,
  SettingsResponse,
  ReplayStateResponse,
  ReportCardResponse,
  MetricsSummaryResponse,
  HabitItem,
  ChainItem,
  ExamRunItem,
} from "../api/types";
import { Badge } from "../components/common/Badge";
import { Button } from "../components/common/Button";
import { ErrorBanner } from "../components/common/ErrorBanner";
import { InsightsView } from "./InsightsView";
import { RadarView } from "./RadarView";

export type MoreSubTab = "insights" | "privacy" | "webfacts" | "ledger" | "settings" | "replay" | "radar";

interface MoreViewProps {
  initialSubTab?: MoreSubTab;
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
  initialSubTab = "insights",
  reportCard,
  metrics,
  habits,
  chains,
  exams,
  onDenyHabit,
  onRunExam,
  radarActive = false,
}) => {
  const [subTab, setSubTab] = useState<MoreSubTab>(initialSubTab);
  const [exposure, setExposure] = useState<ExposureResponse | null>(null);
  const [webFacts, setWebFacts] = useState<WebFactsResponse | null>(null);
  const [ledger, setLedger] = useState<LedgerVerifyResponse | null>(null);
  const [settings, setSettings] = useState<SettingsResponse | null>(null);
  const [replay, setReplay] = useState<ReplayStateResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchSectionData = async () => {
    if (subTab === "insights" || subTab === "radar") {
      return;
    }
    setLoading(true);
    setError(null);
    try {
      if (subTab === "privacy") {
        const data = await apiClient.getExposure();
        setExposure(data);
      } else if (subTab === "webfacts") {
        // Strictly read recorded facts - zero outbound web requests
        const data = await apiClient.getWebFacts();
        setWebFacts(data);
      } else if (subTab === "ledger") {
        const data = await apiClient.verifyLedger();
        setLedger(data);
      } else if (subTab === "settings") {
        const data = await apiClient.getSettings();
        setSettings(data);
      } else if (subTab === "replay") {
        const data = await apiClient.getReplayState();
        setReplay(data);
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load section data");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchSectionData();
  }, [subTab]);

  return (
    <div className="space-y-6">
      {/* Sub-tab Navigation */}
      <div className="flex flex-wrap items-center gap-2 border-b border-border pb-3">
        <button
          onClick={() => setSubTab("insights")}
          className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
            subTab === "insights"
              ? "bg-surface-elevated text-brand border border-border"
              : "text-text-muted hover:text-text-primary hover:bg-surface"
          }`}
        >
          <BarChart3 className="w-3.5 h-3.5" />
          <span>Insights</span>
        </button>

        <button
          onClick={() => setSubTab("privacy")}
          className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
            subTab === "privacy"
              ? "bg-surface-elevated text-brand border border-border"
              : "text-text-muted hover:text-text-primary hover:bg-surface"
          }`}
        >
          <Eye className="w-3.5 h-3.5" />
          <span>Privacy & Exposure</span>
        </button>

        <button
          onClick={() => setSubTab("webfacts")}
          className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
            subTab === "webfacts"
              ? "bg-surface-elevated text-brand border border-border"
              : "text-text-muted hover:text-text-primary hover:bg-surface"
          }`}
        >
          <Globe className="w-3.5 h-3.5" />
          <span>Web Facts Activity</span>
        </button>

        <button
          onClick={() => setSubTab("ledger")}
          className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
            subTab === "ledger"
              ? "bg-surface-elevated text-brand border border-border"
              : "text-text-muted hover:text-text-primary hover:bg-surface"
          }`}
        >
          <ShieldCheck className="w-3.5 h-3.5" />
          <span>Activity Record</span>
        </button>

        <button
          onClick={() => setSubTab("settings")}
          className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
            subTab === "settings"
              ? "bg-surface-elevated text-brand border border-border"
              : "text-text-muted hover:text-text-primary hover:bg-surface"
          }`}
        >
          <Sliders className="w-3.5 h-3.5" />
          <span>Tunables</span>
        </button>

        <button
          onClick={() => setSubTab("replay")}
          className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
            subTab === "replay"
              ? "bg-surface-elevated text-brand border border-border"
              : "text-text-muted hover:text-text-primary hover:bg-surface"
          }`}
        >
          <Play className="w-3.5 h-3.5" />
          <span>Clock Replay</span>
        </button>

        {radarActive && (
          <button
            onClick={() => setSubTab("radar")}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
              subTab === "radar"
                ? "bg-surface-elevated text-brand border border-border"
                : "text-text-muted hover:text-text-primary hover:bg-surface"
            }`}
          >
            <Radio className="w-3.5 h-3.5 text-brand" />
            <span>Radar Board</span>
          </button>
        )}
      </div>

      {error && <ErrorBanner message={error} onRetry={fetchSectionData} />}

      {/* Subtab: Insights */}
      {subTab === "insights" && (
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

      {/* Subtab: Radar (Conditional) */}
      {subTab === "radar" && <RadarView />}

      {/* Subtab: Privacy & Exposure */}
      {subTab === "privacy" && (
        <div className="space-y-6">
          <div className="rounded-xl bg-surface border border-border p-5 space-y-2">
            <h2 className="text-sm font-semibold text-text-primary flex items-center gap-2">
              <Lock className="w-4 h-4 text-brand" />
              <span>Redaction & LLM Exposure Transparency</span>
            </h2>
            <p className="text-xs text-text-muted leading-relaxed">
              Every prompt sent to an external model is scrubbed by deterministic redactors before dispatch.
              Raw mail bodies and personal identifiers are never passed unredacted. Below is the total recorded
              exposure and token cost.
            </p>
          </div>

          {loading ? (
            <div className="h-40 bg-surface rounded-xl border border-border animate-pulse" />
          ) : exposure ? (
            <div className="space-y-4">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div className="p-4 rounded-xl bg-surface border border-border">
                  <div className="text-xs text-text-muted">Total LLM Dispatches</div>
                  <div className="text-xl font-bold text-text-primary mt-1">{exposure.calls}</div>
                </div>
                <div className="p-4 rounded-xl bg-surface border border-border">
                  <div className="text-xs text-text-muted">Incurred Cost (USD)</div>
                  <div className="text-xl font-bold text-brand mt-1">${exposure.total_cost_usd.toFixed(4)}</div>
                </div>
              </div>

              {exposure.breakdown.length === 0 ? (
                <div className="p-6 rounded-xl bg-surface border border-border text-center text-xs text-text-muted">
                  No model calls recorded yet.
                </div>
              ) : (
                <div className="rounded-xl bg-surface border border-border overflow-hidden">
                  <table className="w-full text-xs text-left">
                    <thead className="bg-surface-subtle text-text-muted border-b border-border">
                      <tr>
                        <th className="py-2.5 px-3">Call Kind</th>
                        <th className="py-2.5 px-3">Model</th>
                        <th className="py-2.5 px-3">Calls</th>
                        <th className="py-2.5 px-3">Tokens (In / Out)</th>
                        <th className="py-2.5 px-3 text-right">Cost</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border font-mono">
                      {exposure.breakdown.map((row, idx) => (
                        <tr key={idx} className="hover:bg-surface-elevated/40">
                          <td className="py-2.5 px-3 font-medium text-text-primary">{row.call_kind}</td>
                          <td className="py-2.5 px-3 text-text-muted truncate max-w-[140px]">{row.model_id}</td>
                          <td className="py-2.5 px-3 text-text-primary">{row.calls}</td>
                          <td className="py-2.5 px-3 text-text-muted">
                            {row.tokens_in} / {row.tokens_out}
                          </td>
                          <td className="py-2.5 px-3 text-right text-brand">
                            ${row.cost_usd.toFixed(4)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          ) : null}
        </div>
      )}

      {/* Subtab: Web Facts Activity */}
      {subTab === "webfacts" && (
        <div className="space-y-6">
          <div className="rounded-xl bg-surface border border-border p-5 space-y-2">
            <h2 className="text-sm font-semibold text-text-primary flex items-center gap-2">
              <Globe className="w-4 h-4 text-brand" />
              <span>Recorded Web Activity (Tavily Transparency)</span>
            </h2>
            <p className="text-xs text-text-muted leading-relaxed">
              Viewing this page strictly displays past recorded Tavily activity and verified entity facts.
              It initiates <strong className="text-text-primary">zero outbound requests</strong>.
              All facts are quarantined and can only restrict autonomy, never raise it.
            </p>
          </div>

          {loading ? (
            <div className="h-40 bg-surface rounded-xl border border-border animate-pulse" />
          ) : webFacts ? (
            <div className="space-y-4">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div className="p-4 rounded-xl bg-surface border border-border">
                  <div className="text-xs text-text-muted">Recorded Queries</div>
                  <div className="text-xl font-bold text-text-primary mt-1">{webFacts.total_calls}</div>
                </div>
                <div className="p-4 rounded-xl bg-surface border border-border">
                  <div className="text-xs text-text-muted">Credits Consumed</div>
                  <div className="text-xl font-bold text-brand mt-1">{webFacts.total_credits}</div>
                </div>
              </div>

              <div className="space-y-2">
                <h3 className="text-xs font-semibold uppercase tracking-wider text-text-muted">
                  Quarantined Entity Facts
                </h3>
                {webFacts.entities.length === 0 ? (
                  <div className="p-6 rounded-xl bg-surface border border-border text-center text-xs text-text-muted">
                    No web entity facts stored in database.
                  </div>
                ) : (
                  <div className="space-y-2">
                    {webFacts.entities.map((entity, i) => (
                      <div key={i} className="p-4 rounded-xl bg-surface border border-border space-y-2">
                        <div className="flex items-center justify-between">
                          <span className="text-sm font-medium text-text-primary">{entity.domain}</span>
                          <Badge variant="subtle">{entity.status}</Badge>
                        </div>
                        <div className="text-xs font-mono bg-surface-subtle p-2 rounded border border-border overflow-x-auto text-text-muted">
                          {JSON.stringify(entity.facts, null, 2)}
                        </div>
                        {entity.sources && entity.sources.length > 0 && (
                          <div className="flex flex-wrap gap-2 text-xs">
                            <span className="text-text-muted">Sources:</span>
                            {entity.sources.map((s, idx) => (
                              <a
                                key={idx}
                                href={s.url}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="inline-flex items-center gap-1 text-brand hover:underline"
                              >
                                {s.title || s.url}
                                <ExternalLink className="w-3 h-3" />
                              </a>
                            ))}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          ) : null}
        </div>
      )}

      {/* Subtab: Activity Record & Ledger Verify */}
      {subTab === "ledger" && (
        <div className="space-y-6">
          <div className="rounded-xl bg-surface border border-border p-5 space-y-2">
            <h2 className="text-sm font-semibold text-text-primary flex items-center gap-2">
              <ShieldCheck className="w-4 h-4 text-brand" />
              <span>Immutable Ledger Hash Chain</span>
            </h2>
            <p className="text-xs text-text-muted leading-relaxed">
              Every proposal, human response, executed action, and licence transition is recorded in an append-only,
              SHA-256 hash-chained ledger. Tamper-checking recalculates the full chain up to the head hash.
            </p>
          </div>

          {loading ? (
            <div className="h-40 bg-surface rounded-xl border border-border animate-pulse" />
          ) : ledger ? (
            <div className="space-y-4">
              <div className="p-5 rounded-xl bg-surface border border-border flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div
                    className={`w-10 h-10 rounded-full flex items-center justify-center ${
                      ledger.ok
                        ? "bg-status-success/10 text-status-success"
                        : "bg-status-error/10 text-status-error"
                    }`}
                  >
                    {ledger.ok ? (
                      <CheckCircle2 className="w-6 h-6" />
                    ) : (
                      <AlertTriangle className="w-6 h-6" />
                    )}
                  </div>
                  <div>
                    <h3 className="text-sm font-semibold text-text-primary">
                      {ledger.ok ? "Ledger Cryptographically Intact" : "Ledger Corruption Detected"}
                    </h3>
                    <p className="text-xs text-text-muted">
                      {ledger.ok
                        ? `Chain of ${ledger.length} entries verified without discrepancy`
                        : `Discrepancy identified at sequence ${ledger.seq}`}
                    </p>
                  </div>
                </div>

                <Button variant="ghost" size="sm" onClick={fetchSectionData}>
                  <RefreshCw className="w-4 h-4 mr-1.5" />
                  Re-verify
                </Button>
              </div>

              <div className="p-4 rounded-xl bg-surface border border-border space-y-2">
                <div className="text-xs text-text-muted">Latest Head Hash</div>
                <div className="text-xs font-mono text-brand break-all bg-surface-subtle p-2.5 rounded border border-border">
                  {ledger.head_hash}
                </div>
              </div>
            </div>
          ) : null}
        </div>
      )}

      {/* Subtab: Tunables / Settings */}
      {subTab === "settings" && (
        <div className="space-y-6">
          <div className="rounded-xl bg-surface border border-border p-5 space-y-2">
            <h2 className="text-sm font-semibold text-text-primary flex items-center gap-2">
              <Sliders className="w-4 h-4 text-brand" />
              <span>Effective System Tunables</span>
            </h2>
            <p className="text-xs text-text-muted leading-relaxed">
              Read-only parameters governing statistical licence thresholds, budget caps, and drift alarms.
              Credentials and private tokens are strictly omitted per contract.
            </p>
          </div>

          {loading ? (
            <div className="h-40 bg-surface rounded-xl border border-border animate-pulse" />
          ) : settings ? (
            <div className="rounded-xl bg-surface border border-border overflow-hidden">
              <table className="w-full text-xs text-left">
                <thead className="bg-surface-subtle text-text-muted border-b border-border">
                  <tr>
                    <th className="py-2.5 px-4">Parameter</th>
                    <th className="py-2.5 px-4 font-mono">Effective Value</th>
                    <th className="py-2.5 px-4">Description</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  <tr className="hover:bg-surface-elevated/40">
                    <td className="py-2.5 px-4 font-medium text-text-primary">Clock Mode</td>
                    <td className="py-2.5 px-4 font-mono text-brand">{settings.clock_mode}</td>
                    <td className="py-2.5 px-4 text-text-muted">Clock authority (system or replay)</td>
                  </tr>
                  <tr className="hover:bg-surface-elevated/40">
                    <td className="py-2.5 px-4 font-medium text-text-primary">Budget Cap</td>
                    <td className="py-2.5 px-4 font-mono text-brand">${settings.budget_hard_limit_usd.toFixed(2)} USD</td>
                    <td className="py-2.5 px-4 text-text-muted">Hard spending ceiling</td>
                  </tr>
                  <tr className="hover:bg-surface-elevated/40">
                    <td className="py-2.5 px-4 font-medium text-text-primary">Audit Holdout</td>
                    <td className="py-2.5 px-4 font-mono text-brand">{(settings.audit_fraction * 100).toFixed(0)}%</td>
                    <td className="py-2.5 px-4 text-text-muted">Fraction held for human confirmation</td>
                  </tr>
                  <tr className="hover:bg-surface-elevated/40">
                    <td className="py-2.5 px-4 font-medium text-text-primary">L1 Bounds (Suggest)</td>
                    <td className="py-2.5 px-4 font-mono text-text-primary">
                      n &ge; {settings.l1_min_n}, LB &ge; {settings.l1_min_lb}
                    </td>
                    <td className="py-2.5 px-4 text-text-muted">Min sample count and lower bound</td>
                  </tr>
                  <tr className="hover:bg-surface-elevated/40">
                    <td className="py-2.5 px-4 font-medium text-text-primary">L2 Bounds (Undo)</td>
                    <td className="py-2.5 px-4 font-mono text-text-primary">
                      n &ge; {settings.l2_min_n}, LB &ge; {settings.l2_min_lb}
                    </td>
                    <td className="py-2.5 px-4 text-text-muted">Min sample count and lower bound</td>
                  </tr>
                  <tr className="hover:bg-surface-elevated/40">
                    <td className="py-2.5 px-4 font-medium text-text-primary">L3 Bounds (Silent)</td>
                    <td className="py-2.5 px-4 font-mono text-text-primary">
                      n &ge; {settings.l3_min_n}, LB &ge; {settings.l3_min_lb}
                    </td>
                    <td className="py-2.5 px-4 text-text-muted">Min sample count and lower bound</td>
                  </tr>
                  <tr className="hover:bg-surface-elevated/40">
                    <td className="py-2.5 px-4 font-medium text-text-primary">CUSUM Threshold</td>
                    <td className="py-2.5 px-4 font-mono text-text-primary">{settings.cusum_threshold}</td>
                    <td className="py-2.5 px-4 text-text-muted">Cumulative sum drift trigger</td>
                  </tr>
                  <tr className="hover:bg-surface-elevated/40">
                    <td className="py-2.5 px-4 font-medium text-text-primary">PSI Threshold</td>
                    <td className="py-2.5 px-4 font-mono text-text-primary">{settings.psi_threshold}</td>
                    <td className="py-2.5 px-4 text-text-muted">Population stability index threshold</td>
                  </tr>
                </tbody>
              </table>
            </div>
          ) : null}
        </div>
      )}

      {/* Subtab: Replay Controls */}
      {subTab === "replay" && (
        <div className="space-y-6">
          <div className="rounded-xl bg-surface border border-border p-5 space-y-2">
            <h2 className="text-sm font-semibold text-text-primary flex items-center gap-2">
              <Play className="w-4 h-4 text-brand" />
              <span>Simulated Clock & Replay Control</span>
            </h2>
            <p className="text-xs text-text-muted leading-relaxed">
              In replay mode, temporal isolation is preserved by locking all reads to the simulated clock tick.
              You can play, pause, or adjust speed for backtest evaluations.
            </p>
          </div>

          {loading ? (
            <div className="h-40 bg-surface rounded-xl border border-border animate-pulse" />
          ) : replay ? (
            <div className="rounded-xl bg-surface border border-border p-5 space-y-4">
              <div className="flex items-center justify-between">
                <div>
                  <div className="text-xs text-text-muted">Replay Clock State</div>
                  <div className="text-base font-semibold text-text-primary mt-0.5">
                    {replay.running ? "Running" : "Paused"}
                  </div>
                </div>
                <Badge variant={replay.running ? "success" : "subtle"}>
                  {replay.mode.toUpperCase()}
                </Badge>
              </div>

              <div className="p-3 rounded-lg bg-surface-subtle border border-border text-xs font-mono text-brand">
                Simulated Time: {replay.simulated_date || "Realtime clock active"}
              </div>

              <div className="flex items-center gap-3 pt-2">
                {replay.running ? (
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={async () => {
                      await apiClient.pauseReplay();
                      fetchSectionData();
                    }}
                  >
                    <Pause className="w-4 h-4 mr-1.5" />
                    Pause
                  </Button>
                ) : (
                  <Button
                    variant="primary"
                    size="sm"
                    onClick={async () => {
                      await apiClient.startReplay();
                      fetchSectionData();
                    }}
                  >
                    <Play className="w-4 h-4 mr-1.5" />
                    Start Replay
                  </Button>
                )}

                <div className="flex items-center gap-1.5 ml-auto">
                  <span className="text-xs text-text-muted">Speed:</span>
                  {[1, 5, 20].map((s) => (
                    <button
                      key={s}
                      onClick={async () => {
                        await apiClient.setReplaySpeed(s);
                        fetchSectionData();
                      }}
                      className={`px-2.5 py-1 rounded text-xs font-mono border transition-colors ${
                        replay.speed === s
                          ? "bg-brand text-canvas border-brand font-bold"
                          : "bg-surface-subtle text-text-muted border-border hover:text-text-primary"
                      }`}
                    >
                      {s}x
                    </button>
                  ))}
                </div>
              </div>
            </div>
          ) : null}
        </div>
      )}
    </div>
  );
};
