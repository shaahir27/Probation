import { QueueItem } from "../api/types";
import { EmptyState } from "../components/common/EmptyState";
import { StatePanel } from "../components/common/StatePanel";

interface WatchingViewProps {
  items: QueueItem[];
  errorMessage?: string | null;
  onRetry?(): void;
}

/**
 * Observations with no owner decision. Nothing here implies an action is waiting for
 * approval, and a failed read is never shown as an empty list.
 */
export function WatchingView({ items, errorMessage = null, onRetry }: WatchingViewProps) {
  if (errorMessage !== null) {
    return (
      <StatePanel
        state="error"
        title="Watching list is unavailable"
        description={errorMessage}
        onRetry={onRetry}
        retryLabel="Try again"
      />
    );
  }
  if (items.length === 0) {
    return (
      <EmptyState
        title="Nothing is being watched"
        description="Emails that Probation is observing without a decision will appear here."
      />
    );
  }
  return (
    <section aria-labelledby="watching-title" className="space-y-4">
      <header>
        <h1 id="watching-title" className="font-serif text-2xl">
          Watching
        </h1>
        <p className="mt-1 text-sm text-ink-secondary">
          Probation is keeping an eye on these emails. Nothing will be sent or changed from this list, and nothing here
          is waiting for your approval.
        </p>
      </header>
      <ul className="divide-y border-y border-line">
        {items.map((item) => (
          <li key={item.id} className="py-4">
            <a href={`#/watching/${encodeURIComponent(item.id)}`} className="block min-h-11">
              <span className="block break-words text-sm font-medium text-ink">{item.summary || "Email details unavailable"}</span>
              <span className="mt-1 block text-sm text-ink-secondary">Open details</span>
            </a>
          </li>
        ))}
      </ul>
    </section>
  );
}
