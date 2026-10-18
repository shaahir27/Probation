import { AlertCircle } from "lucide-react";
import { LicenceItem } from "../api/types";
import { Badge } from "../components/common/Badge";
import { EmptyState } from "../components/common/EmptyState";

interface PermissionsViewProps {
  licences: LicenceItem[];
}

export function PermissionsView({ licences }: PermissionsViewProps) {
  if (licences.length === 0) {
    return (
      <EmptyState
        title="No permissions derived yet"
        description="Probation derives permissions per task and action as it observes consistent, high-agreement decisions."
      />
    );
  }

  const getLevelLabel = (level: number) => {
    switch (level) {
      case 0:
        return "Watching";
      case 1:
        return "Suggests";
      case 2:
        return "Does it, with undo";
      case 3:
        return "Does it quietly";
      default:
        return `Level ${level}`;
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-bold text-ink">Earned Permissions</h2>
        <p className="text-sm text-ink-secondary mt-0.5">
          Permissions are earned separately for each kind of task and action. They are mathematically
          derived from your history, never stored as static truth.
        </p>
      </div>

      <div className="space-y-4">
        {licences.map((lic) => {
          const lbPct = Math.round(lic.lower_bound * 100);

          return (
            <div
              key={`${lic.class_key}-${lic.action}`}
              className="p-5 rounded-2xl bg-surface border border-line space-y-4"
            >
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                <div>
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-semibold text-brand">{lic.class_key}</span>
                    <span className="text-ink-tertiary">→</span>
                    <span className="text-sm font-bold text-ink">{lic.action}</span>
                  </div>
                  <div className="text-xs text-ink-tertiary mt-1">
                    Matched you {lic.k_strong} of {lic.n_strong} times (safe estimate {lbPct}%). Last 30 days: {lic.n_recent} checks.
                  </div>
                </div>

                <Badge variant={lic.level >= 2 ? "brand" : lic.level === 1 ? "warning" : "subtle"}>
                  {getLevelLabel(lic.level)}
                </Badge>
              </div>

              {/* 4-Step Autonomy Ladder */}
              <div className="grid grid-cols-4 gap-2 pt-2 border-t border-line">
                {[0, 1, 2, 3].map((step) => {
                  const isActive = lic.level === step;
                  return (
                    <div
                      key={step}
                      className={`p-2 rounded-lg text-center border transition-all ${
                        isActive
                          ? "bg-brand/15 border-brand text-brand font-semibold"
                          : "bg-surfaceSubtle/50 border-line text-ink-tertiary opacity-60"
                      }`}
                    >
                      <div className="text-[10px] uppercase tracking-wider">L{step}</div>
                      <div className="text-xs truncate">{getLevelLabel(step)}</div>
                    </div>
                  );
                })}
              </div>

              {/* Drift status alert if applicable */}
              {lic.drift?.last_alarm_at && (
                <div className="p-3 rounded-xl bg-status-warning/10 border border-status-warning/30 flex items-center gap-2 text-xs text-status-warning">
                  <AlertCircle className="w-4 h-4 shrink-0" />
                  <span>
                    Your habits changed on {lic.drift.last_alarm_at.split("T")[0]}; permission is temporarily held at Suggests until re-tested.
                  </span>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
