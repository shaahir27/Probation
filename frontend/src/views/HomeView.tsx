import { ArrowRight, CheckCircle2, ShieldAlert, Sparkles, Mail, Calendar, FileText, Shield } from "lucide-react";
import { Button } from "../components/common/Button";
import { LicenceItem, QueueItem } from "../api/types";

interface HomeViewProps {
  queueItems: QueueItem[];
  licences: LicenceItem[];
  onNavigate: (tab: string) => void;
}

export function HomeView({ queueItems, licences, onNavigate }: HomeViewProps) {
  const needsAttentionLicences = licences.filter(
    (l) => l.level === 0 || (l.drift && l.drift.last_alarm_at)
  );

  const getPackIcon = (classKey: string) => {
    const k = classKey.toLowerCase();
    if (k.includes("mail") || k.includes("email") || k.includes("recruiter")) return <Mail className="w-4 h-4 text-ink-secondary" />;
    if (k.includes("calendar")) return <Calendar className="w-4 h-4 text-ink-secondary" />;
    if (k.includes("file") || k.includes("doc")) return <FileText className="w-4 h-4 text-ink-secondary" />;
    return <Shield className="w-4 h-4 text-ink-secondary" />;
  };

  return (
    <div className="space-y-6">
      {/* "What Needs You" Editorial Hero Card */}
      <div className="p-6 sm:p-8 rounded-2xl bg-surface border border-line relative overflow-hidden shadow-sm">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-6">
          <div className="space-y-1.5">
            <span className="text-xs font-semibold uppercase tracking-wider text-brand">
              What Needs You
            </span>
            <h2 className="font-serif text-3xl sm:text-4xl font-normal text-ink tracking-tight">
              {queueItems.length > 0
                ? `${queueItems.length} item${queueItems.length > 1 ? "s" : ""} waiting for your review`
                : "Nothing needs you right now"}
            </h2>
            <p className="text-sm text-ink-secondary max-w-xl leading-relaxed">
              {queueItems.length > 0
                ? "Actions are grouped with confidence scores, past similar cases, and instant approval controls."
                : "Probation is operating in shadow mode or executing permitted routine tasks."}
            </p>
          </div>

          <div className="shrink-0">
            {queueItems.length > 0 ? (
              <button
                onClick={() => onNavigate("queue")}
                className="bg-[#C8B27D] hover:bg-[#D4C08D] text-[#111B18] font-semibold px-5 py-3 rounded-xl text-sm transition-colors flex items-center gap-2 shadow-sm active:scale-95"
              >
                <span>Review Queue</span>
                <ArrowRight className="w-4 h-4 stroke-[2.5]" />
              </button>
            ) : (
              <Button variant="secondary" onClick={() => onNavigate("permissions")}>
                <span>Inspect Permissions</span>
              </Button>
            )}
          </div>
        </div>
      </div>

      {/* Permissions Needing Attention */}
      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-ink-secondary">
            Permissions Needing Attention
          </h3>
          <button
            onClick={() => onNavigate("permissions")}
            className="text-xs text-brand hover:underline font-medium"
          >
            View all ({licences.length})
          </button>
        </div>

        {needsAttentionLicences.length === 0 ? (
          <div className="p-5 rounded-2xl bg-surface border border-line text-sm text-ink-secondary flex items-center gap-3">
            <CheckCircle2 className="w-5 h-5 text-[#85B99A] shrink-0" />
            <span>All active permissions are stable with no active habit-shift alarms.</span>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {needsAttentionLicences.slice(0, 4).map((l) => (
              <div
                key={`${l.class_key}-${l.action}`}
                onClick={() => onNavigate("permissions")}
                className="p-4 rounded-xl bg-surface border border-line hover:border-brand/30 transition-all cursor-pointer space-y-3 shadow-sm"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="flex items-start gap-3">
                    <div className="w-9 h-9 rounded-lg bg-surfaceSubtle border border-line flex items-center justify-center shrink-0">
                      {getPackIcon(l.class_key)}
                    </div>
                    <div>
                      <h4 className="text-sm font-semibold text-ink">
                        {l.title || l.class_key}
                      </h4>
                      <p className="text-xs text-ink-secondary mt-0.5">
                        {l.action_label || l.action}
                      </p>
                    </div>
                  </div>

                  {l.drift?.last_alarm_at ? (
                    <span className="inline-flex items-center gap-1 text-[11px] font-semibold text-[#E0B663] bg-[#E0B663]/15 px-2 py-0.5 rounded-full border border-[#E0B663]/30 shrink-0">
                      <ShieldAlert className="w-3 h-3" />
                      Habit Shift
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1 text-[11px] font-semibold text-ink-tertiary bg-surfaceSubtle px-2 py-0.5 rounded-full border border-line shrink-0">
                      Restricted
                    </span>
                  )}
                </div>

                <div className="pt-2 border-t border-line flex items-center justify-between text-xs text-ink-tertiary">
                  <span>Safe estimate: <strong className="text-ink">{Math.round(l.lower_bound * 100)}%</strong></span>
                  <span>{l.k_strong}/{l.n_strong} agreements</span>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* Driving Test Philosophy Card */}
      <div className="p-5 rounded-2xl bg-surfaceRaised border border-line text-xs text-ink-secondary leading-relaxed flex items-start gap-3.5">
        <Sparkles className="w-5 h-5 text-brand shrink-0 mt-0.5" />
        <div>
          <strong className="text-ink font-semibold">How trust is earned: </strong>
          Probation never acts on high-stakes operations without mathematical proof on your own past data
          (Clopper-Pearson 95% lower bound) and passing adversarial invariance exams. If your habits shift or mistakes occur, permissions are automatically demoted until re-tested.
        </div>
      </div>
    </div>
  );
}
