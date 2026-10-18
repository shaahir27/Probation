import { ArrowRight, CheckCircle2 } from "lucide-react";
import { Button } from "../components/common/Button";
import { Badge } from "../components/common/Badge";
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

  return (
    <div className="space-y-6">
      {/* "What Needs Me Now?" Hero Card */}
      <div className="p-6 rounded-2xl bg-surface border border-line relative overflow-hidden">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div>
            <span className="text-xs font-semibold uppercase tracking-wider text-brand">
              What Needs You
            </span>
            <h2 className="text-2xl font-bold text-ink mt-1">
              {queueItems.length > 0
                ? `${queueItems.length} item${queueItems.length > 1 ? "s" : ""} waiting for your review`
                : "Nothing needs you right now"}
            </h2>
            <p className="text-sm text-ink-secondary mt-1 max-w-xl">
              {queueItems.length > 0
                ? "Routine items are grouped by task kind with inline decision buttons."
                : "Probation is watching in shadow mode or acting on authorized high-confidence tasks."}
            </p>
          </div>

          {queueItems.length > 0 ? (
            <Button variant="primary" size="lg" onClick={() => onNavigate("queue")}>
              <span>Review Queue</span>
              <ArrowRight className="w-4 h-4" />
            </Button>
          ) : (
            <Button variant="secondary" onClick={() => onNavigate("permissions")}>
              <span>Inspect Permissions</span>
            </Button>
          )}
        </div>
      </div>

      {/* Permissions Needing Attention */}
      <section>
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-semibold uppercase tracking-wider text-ink-secondary">
            Permissions Needing Attention
          </h3>
          <button
            onClick={() => onNavigate("permissions")}
            className="text-xs text-brand hover:underline"
          >
            View all ({licences.length})
          </button>
        </div>

        {needsAttentionLicences.length === 0 ? (
          <div className="p-4 rounded-xl bg-surface border border-line text-sm text-ink-secondary flex items-center gap-2">
            <CheckCircle2 className="w-4 h-4 text-status-success" />
            <span>All active permissions are stable with no unhandled alarms.</span>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {needsAttentionLicences.slice(0, 4).map((l) => (
              <div key={`${l.class_key}-${l.action}`} className="p-4 rounded-xl bg-surface border border-line">
                <div className="flex items-start justify-between">
                  <div>
                    <h4 className="text-sm font-semibold text-ink">{l.class_key}</h4>
                    <p className="text-xs text-ink-secondary mt-0.5">Proposed action: {l.action}</p>
                  </div>
                  <Badge variant={l.drift?.last_alarm_at ? "warning" : "subtle"}>
                    {l.drift?.last_alarm_at ? "Habit Shift" : "Watching"}
                  </Badge>
                </div>
                <div className="text-xs text-ink-tertiary mt-3">
                  Safe estimate: {Math.round(l.lower_bound * 100)}% ({l.k_strong}/{l.n_strong} agreements)
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* Quick Summary of Driving Test Philosophy */}
      <div className="p-4 rounded-xl bg-surfaceSubtle/50 border border-line text-xs text-ink-secondary leading-relaxed">
        <strong className="text-ink font-semibold">How trust is earned:</strong> Probation never
        acts on high-stakes operations without statistical proof on your own past data ($LB_{`{0.95}`}$)
        and passing trick-question exams. If your habits shift or mistakes occur, permissions are
        automatically demoted until a fresh exam passes.
      </div>
    </div>
  );
}
