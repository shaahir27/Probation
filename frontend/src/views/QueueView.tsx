import { ArrowUpRight, Inbox } from "lucide-react";
import { QueueDigest, QueueGroup, QueueItem } from "../api/types";
import { EmptyState } from "../components/common/EmptyState";
import { QUEUE_GATES, QueueGate } from "../navigation";
import { reviewActionLabel } from "../components/queue/ReviewForm";
import { parseEmailText, senderDisplay } from "../lib/emailText";

interface QueueViewProps {
  items: QueueItem[];
  digests: QueueDigest[];
  handledCount: number;
  handledDigests: QueueGroup[];
  expiredCount: number;
  expiredDigests: QueueGroup[];
  gate: QueueGate;
  onGateChange(gate: QueueGate): void;
  onSelectItem?: (item: QueueItem) => void;
  selectedId?: string | null;
}
const GATE_LABEL: Record<QueueGate, string> = { all: "All emails", ask: "Needs your decision", suggest: "Suggested for you" };

export function QueueView({
  items,
  digests,
  handledCount,
  handledDigests,
  expiredCount,
  expiredDigests,
  gate,
  onGateChange,
  onSelectItem,
  selectedId = null,
}: QueueViewProps) {
  const visible = items.filter((item) => gate === "all" || item.gate === gate.toUpperCase());
  const Title = selectedId ? "h2" : "h1";
  const handledFor = (item: QueueItem) =>
    handledDigests.find((group) => group.class_key === item.class_key && group.action === item.action);
  return <section aria-labelledby="review-title" className="space-y-4" data-ui="email-review">
    <header className="space-y-3">
      <div className="flex flex-wrap items-end justify-between gap-2"><div><Title id="review-title" className="font-serif text-[26px] font-normal leading-none tracking-[-0.02em]">Review</Title><p className="mt-2 text-xs text-ink-secondary">A suggestion is a starting point. You decide what happens next.</p></div><p className="text-xs text-ink-tertiary tabular-nums" aria-live="polite">{visible.length} waiting{visible.length === items.length ? "" : ` of ${items.length}`}</p></div>
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line"><div role="group" aria-label="Filter by what is waiting" className="flex flex-wrap gap-x-4">{QUEUE_GATES.map((option) => <button key={option} type="button" aria-pressed={gate === option} onClick={() => onGateChange(option)} className="review-tab">{GATE_LABEL[option]}</button>)}</div><a href="#/watching" className="min-h-11 inline-flex items-center gap-1.5 text-xs text-ink-secondary">Watching only<ArrowUpRight size={13} aria-hidden="true" /></a></div>
      {digests.length > 0 && <p className="text-xs leading-5 text-ink-secondary">{digests.map((group) => `${group.count} waiting for ${reviewActionLabel(group.action).toLowerCase()}`).join(" · ")}</p>}
    </header>
    {items.length === 0 ? <EmptyState title="Nothing needs your decision" description="New emails that need your review will appear here." icon={<Inbox className="h-6 w-6" aria-hidden="true" />} /> : visible.length === 0 ? <p className="border-t border-line py-6 text-sm text-ink-secondary">No emails match this filter.</p> : <ul className="inbox-list">{visible.map((item, index) => {
      const text = parseEmailText(item.summary);
      const primary = index === 0 && selectedId === null;
      return <li key={item.id} data-selected={selectedId === item.id ? "true" : undefined} className="inbox-row">
        <span className="mail-identity" aria-hidden="true">{(item.sender_key || "E").charAt(0).toUpperCase()}</span>
        <div className="min-w-0">
          <p className="mb-1 max-w-[36ch] truncate text-xs text-ink-tertiary">{senderDisplay(item.sender_key)}</p>
          <p className="inbox-subject">{text.subject}</p>
          {text.preview && <p className="inbox-preview">{text.preview}</p>}
          <p className="inbox-meta"><span className={item.gate === "SUGGEST" ? "text-brand" : ""}>{item.gate === "SUGGEST" ? "Suggested for you" : "Needs your decision"}</span><span aria-hidden="true" className="mx-2">·</span>{reviewActionLabel(item.action)}{item.audit_holdout && " · Spot check"}{handledFor(item) && <span> · From {handledFor(item)!.count} recorded decisions</span>}</p>
        </div>
        <button type="button" aria-label="Review email" title="Review email" onClick={() => onSelectItem?.(item)} className={`inbox-open ${primary ? "is-primary bg-ink text-canvas" : ""}`}>
          <ArrowUpRight size={16} aria-hidden="true" />
        </button>
      </li>;
    })}</ul>}
    {handledCount > 0 && <div className="rounded-xl border border-line bg-surface p-4 text-sm text-ink-secondary">
      <p><strong className="font-medium text-ink">{handledCount} earlier decisions are already recorded.</strong> They are the history behind these permissions, not work on this list.</p>
      <a href="#/permissions" className="mt-2 inline-flex min-h-11 items-center text-sm underline underline-offset-4">See the evidence</a>
    </div>}
    {expiredCount > 0 && <p className="text-xs text-ink-tertiary">{expiredCount} earlier items expired without a decision{expiredDigests.length ? ` across ${expiredDigests.length} task groups` : ""}.</p>}
    <p className="text-xs text-ink-tertiary">Probation has not acted on any email in this list.</p>
  </section>;
}
