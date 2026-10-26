import { QueueItem } from "../api/types";
import { Button } from "../components/common/Button";
import { EmptyState } from "../components/common/EmptyState";
import { QUEUE_GATES, QueueGate } from "../navigation";

interface QueueViewProps {
  items: QueueItem[];
  gate: QueueGate;
  onGateChange(gate: QueueGate): void;
  onSelectItem?: (item: QueueItem) => void;
}

const actionLabel = (action: string): string => {
  const known: Record<string, string> = {
    ARCHIVE: "Archive email",
    TRASH: "Move to trash",
    REPLY: "Send this reply",
    FORWARD: "Forward email",
    LEAVE: "Leave as is",
    PREPARE_DECLINE_DRAFT: "Prepare a reply",
  };
  return known[action] ?? action.replace(/[_|]/g, " ").toLowerCase();
};

const GATE_LABEL: Record<QueueGate, string> = { all: "All", ask: "Needs your decision", suggest: "Suggested for you" };

export function QueueView({ items, gate, onGateChange, onSelectItem }: QueueViewProps) {
  const visible = items.filter((item) => (gate === "all" ? true : item.gate === gate.toUpperCase()));

  return (
    <section aria-labelledby="review-title" className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 id="review-title" className="font-serif text-2xl font-normal text-ink">
            Review
          </h1>
          <p className="mt-1 text-sm text-ink-secondary">
            Emails waiting for your decision. Probation has not acted on any of them.
          </p>
        </div>
        <p className="text-sm text-ink-secondary" aria-live="polite">
          {visible.length} waiting{visible.length === items.length ? "" : ` of ${items.length} in total`}
        </p>
      </div>

      <div role="group" aria-label="Filter by what is waiting" className="flex flex-wrap gap-2">
        {QUEUE_GATES.map((option) => (
          <button
            key={option}
            type="button"
            aria-pressed={gate === option}
            onClick={() => onGateChange(option)}
            className={`min-h-11 rounded-xl border px-3 py-2 text-sm ${
              gate === option ? "border-brand/40 bg-surfaceRaised text-ink" : "border-line bg-surface text-ink-secondary"
            }`}
          >
            {GATE_LABEL[option]}
          </button>
        ))}
      </div>

      {items.length === 0 ? (
        <EmptyState title="Nothing needs your decision" description="New emails that need your review will appear here." />
      ) : visible.length === 0 ? (
        <p className="rounded-xl border border-line bg-surface p-4 text-sm text-ink-secondary">
          No emails match this filter.
        </p>
      ) : (
        <ul className="divide-y border-y border-line">
          {visible.map((item) => (
            <li key={item.id} className="py-4 sm:py-5">
              <article className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2 text-sm">
                    <span className="font-medium text-ink">
                      {item.gate === "SUGGEST" ? "Suggested for you" : "Needs your decision"}
                    </span>
                    <span aria-hidden="true" className="text-ink-tertiary">
                      ·
                    </span>
                    <span className="text-ink-secondary">{actionLabel(item.action)}</span>
                    {item.audit_holdout && <span className="text-ink-tertiary">· Spot check</span>}
                  </div>
                  <p className="mt-1 break-words text-sm text-ink-secondary line-clamp-2">
                    {item.summary || "Email details are not available."}
                  </p>
                </div>
                <div className="flex flex-wrap items-center gap-2 sm:justify-end">
                  <Button size="md" variant="primary" onClick={() => onSelectItem?.(item)}>
                    Review email
                  </Button>
                </div>
              </article>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
