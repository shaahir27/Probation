import { useState } from "react";
import { Check, X, Edit3, Info, FileText } from "lucide-react";
import { QueueItem } from "../api/types";
import { Button } from "../components/common/Button";
import { Badge } from "../components/common/Badge";
import { EmptyState } from "../components/common/EmptyState";

interface QueueViewProps {
  items: QueueItem[];
  onRespond: (id: string, response: "accept" | "reject" | "edit", editedAction?: string) => Promise<void>;
}

export function QueueView({ items, onRespond }: QueueViewProps) {
  const [selectedId, setSelectedId] = useState<string | null>(items[0]?.id || null);
  const [isResponding, setIsResponding] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [customAction, setCustomAction] = useState("");

  const selectedItem = items.find((i) => i.id === selectedId) || items[0];

  const handleAction = async (id: string, response: "accept" | "reject" | "edit", actionName?: string) => {
    setIsResponding(true);
    try {
      await onRespond(id, response, actionName);
      if (selectedId === id) {
        const remaining = items.filter((i) => i.id !== id);
        setSelectedId(remaining[0]?.id || null);
      }
      setEditingId(null);
      setCustomAction("");
    } finally {
      setIsResponding(false);
    }
  };

  if (items.length === 0) {
    return (
      <EmptyState
        title="Queue is empty"
        description="All pending items have been reviewed or resolved. Nothing needs your decision right now."
      />
    );
  }

  return (
    <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
      {/* Left List Pane (12 on mobile, 5 on desktop) */}
      <div className="lg:col-span-5 space-y-3">
        <div className="text-xs text-ink-secondary font-semibold uppercase tracking-wider mb-2">
          Waiting Items ({items.length})
        </div>

        {items.map((item) => {
          const isSelected = selectedItem?.id === item.id;
          return (
            <div
              key={item.id}
              onClick={() => setSelectedId(item.id)}
              className={`p-4 rounded-xl border transition-all cursor-pointer select-none ${
                isSelected
                  ? "bg-surfaceRaised border-brand/40 shadow-sm"
                  : "bg-surface border-line hover:border-brand/20"
              }`}
            >
              <div className="flex items-start justify-between gap-2">
                <span className="text-xs font-semibold text-brand truncate max-w-[200px]">
                  {item.class_key}
                </span>
                <Badge variant={item.gate === "ASK" ? "warning" : "brand"}>
                  {item.gate === "ASK" ? "Needs you" : "Ready for you"}
                </Badge>
              </div>

              <h4 className="text-sm font-medium text-ink mt-1.5 line-clamp-1">{item.summary}</h4>

              <div className="text-xs text-ink-tertiary mt-2 flex items-center justify-between">
                <span>Proposed: <strong className="text-ink font-semibold">{item.action}</strong></span>
                {item.audit_holdout && (
                  <span className="text-status-warning font-medium text-[11px]">Spot check</span>
                )}
              </div>

              {/* Inline Quick Decision Bar */}
              <div className="mt-3 pt-3 border-t border-line flex items-center gap-2">
                <Button
                  size="sm"
                  variant="primary"
                  disabled={isResponding}
                  onClick={(e) => {
                    e.stopPropagation();
                    handleAction(item.id, "accept");
                  }}
                  className="flex-1 text-xs"
                >
                  <Check className="w-3.5 h-3.5" />
                  <span>Do it</span>
                </Button>

                <Button
                  size="sm"
                  variant="secondary"
                  disabled={isResponding}
                  onClick={(e) => {
                    e.stopPropagation();
                    handleAction(item.id, "reject");
                  }}
                  className="flex-1 text-xs text-status-danger"
                >
                  <X className="w-3.5 h-3.5" />
                  <span>Not this</span>
                </Button>

                <Button
                  size="sm"
                  variant="ghost"
                  disabled={isResponding}
                  onClick={(e) => {
                    e.stopPropagation();
                    setSelectedId(item.id);
                    setEditingId(item.id);
                  }}
                  className="px-2"
                  title="Change action"
                >
                  <Edit3 className="w-3.5 h-3.5 text-ink-secondary" />
                </Button>
              </div>
            </div>
          );
        })}
      </div>

      {/* Right Detail Pane (12 on mobile, 7 on desktop) */}
      <div className="lg:col-span-7 bg-surface border border-line rounded-2xl p-6 space-y-6">
        {selectedItem ? (
          <>
            <div>
              <div className="flex items-center gap-2">
                <Badge variant="subtle">{selectedItem.family}</Badge>
                {selectedItem.audit_holdout && (
                  <Badge variant="warning">Audit Holdout</Badge>
                )}
              </div>
              <h3 className="text-lg font-bold text-ink mt-2">{selectedItem.summary}</h3>
              <p className="text-xs text-ink-tertiary mt-1">
                Sender: {selectedItem.sender_key || "Unknown origin"} · Occurred at: {selectedItem.occurred_at}
              </p>
            </div>

            {/* Explanation & Why */}
            <div className="p-4 rounded-xl bg-surfaceSubtle border border-line space-y-3">
              <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-ink">
                <Info className="w-4 h-4 text-brand" />
                <span>Why this recommendation?</span>
              </div>
              <p className="text-sm text-ink-secondary">
                {selectedItem.explanation.summary_reason || "Based on consistent past actions in your timeline."}
              </p>
              {selectedItem.explanation.top_clues && selectedItem.explanation.top_clues.length > 0 && (
                <ul className="text-xs text-ink-secondary list-disc pl-4 space-y-1">
                  {selectedItem.explanation.top_clues.map((clue, idx) => (
                    <li key={idx}>{clue}</li>
                  ))}
                </ul>
              )}
            </div>

            {/* Draft preview if available */}
            {selectedItem.draft && (
              <div className="p-4 rounded-xl bg-surfaceSubtle border border-line space-y-2">
                <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-ink">
                  <FileText className="w-4 h-4 text-brand" />
                  <span>Draft Preview</span>
                </div>
                <div className="p-3 rounded-lg bg-surface border border-line font-mono text-xs text-ink whitespace-pre-wrap">
                  {selectedItem.draft.body_text}
                </div>
              </div>
            )}

            {/* Change Action Form */}
            {editingId === selectedItem.id && (
              <div className="p-4 rounded-xl bg-surfaceRaised border border-brand/40 space-y-3">
                <span className="text-xs font-semibold text-brand uppercase">Change Action</span>
                <input
                  type="text"
                  placeholder="e.g. ARCHIVE, SNOOZE, STAR"
                  value={customAction}
                  onChange={(e) => setCustomAction(e.target.value.toUpperCase())}
                  className="w-full px-3 py-2 text-sm rounded-lg bg-surface border border-line text-ink focus:outline-none focus:ring-1 focus:ring-focus font-mono"
                />
                <div className="flex gap-2">
                  <Button
                    size="sm"
                    variant="primary"
                    disabled={!customAction || isResponding}
                    onClick={() => handleAction(selectedItem.id, "edit", customAction)}
                  >
                    Confirm change
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => setEditingId(null)}>
                    Cancel
                  </Button>
                </div>
              </div>
            )}

            {/* Action Decision Row */}
            <div className="pt-4 border-t border-line flex flex-wrap items-center justify-between gap-3">
              <span className="text-xs text-ink-secondary">
                Decision: <strong className="text-ink">{selectedItem.action}</strong>
              </span>

              <div className="flex items-center gap-3">
                <Button
                  variant="secondary"
                  disabled={isResponding}
                  onClick={() => handleAction(selectedItem.id, "reject")}
                  className="text-status-danger"
                >
                  <X className="w-4 h-4" />
                  <span>Not this</span>
                </Button>
                <Button
                  variant="primary"
                  disabled={isResponding}
                  onClick={() => handleAction(selectedItem.id, "accept")}
                >
                  <Check className="w-4 h-4" />
                  <span>Do it</span>
                </Button>
              </div>
            </div>
          </>
        ) : (
          <div className="text-center py-12 text-sm text-ink-secondary">
            Select an item on the left to inspect details.
          </div>
        )}
      </div>
    </div>
  );
}
