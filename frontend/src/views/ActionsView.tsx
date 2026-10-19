import { useState } from "react";
import {
  Undo2,
  Clock,
  AlertTriangle,
  RotateCcw,
  Ban,
  Mail,
  Calendar,
  FileText,
  Zap,
} from "lucide-react";
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
  const [filter, setFilter] = useState<"all" | "held" | "done" | "undone">("all");

  const handleUndo = async (id: string) => {
    setLoadingId(id);
    try {
      await onUndo(id);
    } finally {
      setLoadingId(null);
    }
  };

  const heldActions = actions.filter((a) => a.status === "HELD");
  const filteredActions = actions.filter((a) => {
    if (filter === "held") return a.status === "HELD";
    if (filter === "done") return a.status === "DONE";
    if (filter === "undone") return a.status === "UNDONE";
    return true;
  });

  const getPackIcon = (pack: string) => {
    const p = pack.toLowerCase();
    if (p.includes("mail") || p.includes("email")) return <Mail className="w-4 h-4 text-ink-secondary" />;
    if (p.includes("calendar")) return <Calendar className="w-4 h-4 text-ink-secondary" />;
    if (p.includes("file") || p.includes("doc")) return <FileText className="w-4 h-4 text-ink-secondary" />;
    return <Zap className="w-4 h-4 text-ink-secondary" />;
  };

  const getStatusBadge = (status: string) => {
    switch (status) {
      case "HELD":
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-semibold bg-[#E0B663]/15 text-[#E0B663] border border-[#E0B663]/30">
            <span className="w-1.5 h-1.5 rounded-full bg-[#E0B663] animate-ping" />
            Held (Can Cancel)
          </span>
        );
      case "DONE":
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-semibold bg-[#85B99A]/15 text-[#85B99A] border border-[#85B99A]/30">
            <span className="w-1.5 h-1.5 rounded-full bg-[#85B99A]" />
            Completed
          </span>
        );
      case "UNDONE":
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-semibold bg-surfaceSubtle text-ink-secondary border border-line">
            <RotateCcw className="w-3 h-3 text-ink-tertiary" />
            Undone
          </span>
        );
      case "CANCELLED":
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-semibold bg-surfaceSubtle text-ink-secondary border border-line">
            <Ban className="w-3 h-3 text-ink-tertiary" />
            Cancelled
          </span>
        );
      case "FAILED":
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-semibold bg-[#E28F88]/15 text-[#E28F88] border border-[#E28F88]/30">
            <AlertTriangle className="w-3 h-3 text-[#E28F88]" />
            Failed
          </span>
        );
      default:
        return <Badge>{status}</Badge>;
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

  return (
    <div className="space-y-6">
      {/* Editorial Header */}
      <div>
        <h1 className="font-serif text-3xl sm:text-4xl font-normal text-ink tracking-tight">
          Actions
        </h1>
        <p className="text-sm text-ink-secondary mt-1">
          Review executed, pending, and reversible operations with full auditability.
        </p>
      </div>

      {/* Prominent Active Hold Hero Card (if any actions are in HELD state) */}
      {heldActions.length > 0 && (
        <div className="p-6 rounded-2xl bg-gradient-to-br from-[#131F1C] to-surface border border-[#E0B663]/40 shadow-lg space-y-4">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
            <div className="flex items-start gap-4">
              {/* Animated Circular Progress Visualizer */}
              <div className="relative w-14 h-14 rounded-full bg-surfaceSubtle border-2 border-[#E0B663] flex items-center justify-center shrink-0 shadow-inner">
                <Clock className="w-6 h-6 text-[#E0B663] animate-pulse" />
                <span className="absolute -top-1 -right-1 w-3 h-3 rounded-full bg-[#E0B663] animate-ping" />
              </div>

              <div>
                <div className="flex items-center gap-2">
                  <span className="text-xs font-bold uppercase tracking-wider text-[#E0B663]">
                    Outgoing Action Hold Active
                  </span>
                  <span className="text-xs text-ink-tertiary">· 10-minute safety buffer</span>
                </div>

                <h3 className="text-lg font-bold text-ink mt-0.5">
                  {heldActions[0].summary || `Pending ${heldActions[0].type}`}
                </h3>

                <p className="text-xs text-ink-secondary mt-1">
                  Executing automatically unless cancelled. Undo state recorded in hash ledger.
                </p>
              </div>
            </div>

            <Button
              size="md"
              variant="danger"
              disabled={loadingId === heldActions[0].id}
              onClick={() => handleUndo(heldActions[0].id)}
              className="shrink-0 font-semibold px-5 py-2.5 shadow-md hover:shadow-lg"
            >
              <Ban className="w-4 h-4 mr-1.5" />
              <span>Cancel Action</span>
            </Button>
          </div>

          <div className="pt-3 border-t border-line/60 flex items-center justify-between text-xs text-ink-tertiary">
            <span>Action ID: <code className="font-mono text-ink">{heldActions[0].id}</code></span>
            <span>Target Pack: <strong className="text-ink">{heldActions[0].pack}</strong></span>
          </div>
        </div>
      )}

      {/* Filter Tabs & History List */}
      <div className="space-y-4">
        <div className="flex items-center justify-between gap-4 border-b border-line pb-3">
          <div className="flex items-center gap-2">
            {(["all", "held", "done", "undone"] as const).map((tab) => (
              <button
                key={tab}
                onClick={() => setFilter(tab)}
                className={`px-3 py-1.5 rounded-lg text-xs font-semibold capitalize transition-colors ${
                  filter === tab
                    ? "bg-surfaceRaised text-brand border border-brand/30"
                    : "text-ink-secondary hover:text-ink hover:bg-surfaceSubtle"
                }`}
              >
                {tab} ({tab === "all" ? actions.length : actions.filter((a) => a.status.toLowerCase() === tab).length})
              </button>
            ))}
          </div>

          <div className="text-xs text-ink-tertiary">
            Ledger-verified actions
          </div>
        </div>

        {/* Action Cards */}
        <div className="space-y-3">
          {filteredActions.map((act) => {
            const isHeld = act.status === "HELD";
            const isDone = act.status === "DONE";
            const canUndo = isHeld || (isDone && act.recallable);

            return (
              <div
                key={act.id}
                className="p-5 rounded-2xl bg-surface border border-line space-y-3 hover:border-brand/30 transition-all shadow-sm"
              >
                <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-3">
                  <div className="flex items-start gap-3.5">
                    <div className="w-10 h-10 rounded-xl bg-surfaceSubtle border border-line flex items-center justify-center shrink-0">
                      {getPackIcon(act.pack)}
                    </div>
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="text-xs font-semibold text-brand uppercase tracking-wider">
                          {act.pack}
                        </span>
                        <span className="text-ink-tertiary">·</span>
                        <span className="text-sm font-bold text-ink">{act.type}</span>
                        {getStatusBadge(act.status)}
                      </div>

                      <p className="text-xs sm:text-sm text-ink-secondary mt-1">
                        {act.summary || "Action committed per licence level."}
                      </p>
                    </div>
                  </div>

                  {canUndo && (
                    <Button
                      size="sm"
                      variant={isHeld ? "danger" : "secondary"}
                      disabled={loadingId === act.id}
                      onClick={() => handleUndo(act.id)}
                      className="shrink-0 text-xs px-3 py-1.5 gap-1.5 self-end sm:self-auto"
                    >
                      <Undo2 className="w-3.5 h-3.5" />
                      <span>{isHeld ? "Cancel Hold" : "Undo Action"}</span>
                    </Button>
                  )}
                </div>

                {/* Recessed Parameters Preview if present */}
                {act.params && Object.keys(act.params).length > 0 && (
                  <div className="bg-[#131F1C] border border-[#344840]/60 rounded-xl p-3 text-xs font-mono text-ink-secondary space-y-1">
                    {Object.entries(act.params).map(([k, v]) => (
                      <div key={k} className="flex gap-2 truncate">
                        <span className="text-ink-tertiary">{k}:</span>
                        <span className="text-ink truncate">{String(v)}</span>
                      </div>
                    ))}
                  </div>
                )}

                <div className="pt-2 border-t border-line flex items-center justify-between text-xs text-ink-tertiary">
                  <div className="flex items-center gap-3">
                    <span>ID: <code className="font-mono text-[11px] text-ink">{act.id}</code></span>
                    <span>Created: {act.created_at.split("T")[0]} {act.created_at.split("T")[1]?.slice(0, 5)}</span>
                  </div>
                  {act.recallable && isDone && (
                    <span className="text-[#85B99A] font-medium text-[11px]">
                      Reversible operation
                    </span>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
