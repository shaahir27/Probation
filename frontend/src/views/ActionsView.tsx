import { useState } from "react";
import { Undo2 } from "lucide-react";
import { ActionItem } from "../api/types";
import { Button } from "../components/common/Button";
import { Badge } from "../components/common/Badge";
import { EmptyState } from "../components/common/EmptyState";

interface ActionsViewProps {
  actions: ActionItem[];
  onUndo: (actionId: string) => Promise<void>;
}

export function ActionsView({ actions, onUndo }: ActionsViewProps) {
  const [loadingId, setLoadingId] = useState<string | null>(null);

  const handleUndo = async (id: string) => {
    setLoadingId(id);
    try {
      await onUndo(id);
    } finally {
      setLoadingId(null);
    }
  };

  if (actions.length === 0) {
    return (
      <EmptyState
        title="No actions recorded"
        description="Completed, held, and undone actions will appear here as the system processes items."
      />
    );
  }

  const getStatusBadge = (status: string) => {
    switch (status) {
      case "HELD":
        return <Badge variant="warning">Will do soon (Held)</Badge>;
      case "DONE":
        return <Badge variant="success">Completed</Badge>;
      case "UNDONE":
        return <Badge variant="subtle">Undone</Badge>;
      case "CANCELLED":
        return <Badge variant="subtle">Cancelled</Badge>;
      case "FAILED":
        return <Badge variant="danger">Failed</Badge>;
      default:
        return <Badge>{status}</Badge>;
    }
  };

  return (
    <div className="space-y-4">
      <div className="text-xs text-ink-secondary font-semibold uppercase tracking-wider mb-2">
        Activity & Action History ({actions.length})
      </div>

      <div className="space-y-3">
        {actions.map((act) => {
          const isHeld = act.status === "HELD";
          const isDone = act.status === "DONE";
          const canUndo = (isHeld || (isDone && act.recallable));

          return (
            <div
              key={act.id}
              className="p-4 rounded-xl bg-surface border border-line flex flex-col sm:flex-row sm:items-center justify-between gap-4"
            >
              <div className="space-y-1">
                <div className="flex items-center gap-2">
                  <span className="text-xs font-semibold text-brand">{act.pack}</span>
                  <span className="text-ink-tertiary">·</span>
                  <span className="text-sm font-semibold text-ink">{act.type}</span>
                  {getStatusBadge(act.status)}
                </div>

                <p className="text-sm text-ink-secondary">{act.summary || "Action performed"}</p>

                <div className="text-xs text-ink-tertiary flex items-center gap-3">
                  <span>ID: <code className="font-mono text-[11px]">{act.id}</code></span>
                  <span>Time: {act.created_at}</span>
                  {isHeld && act.hold_until && (
                    <span className="text-status-warning font-medium">
                      Hold expires at: {act.hold_until.split("T")[1].slice(0, 5)}
                    </span>
                  )}
                </div>
              </div>

              {canUndo && (
                <div className="shrink-0">
                  <Button
                    size="sm"
                    variant={isHeld ? "danger" : "secondary"}
                    disabled={loadingId === act.id}
                    onClick={() => handleUndo(act.id)}
                    className="gap-1.5"
                  >
                    <Undo2 className="w-3.5 h-3.5" />
                    <span>{isHeld ? "Cancel Hold" : "Undo"}</span>
                  </Button>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
