import { ArrowRight, ArrowUpRight, Inbox } from "lucide-react";
import { QueueDigest, QueueGroup, QueueItem } from "../api/types";
import { Button } from "../components/common/Button";
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
const gateLabel = (item: QueueItem) => (item.gate === "SUGGEST" ? "Suggested for you" : "Needs your decision");
const initial = (item: QueueItem) => (item.sender_key || "E").charAt(0).toUpperCase();

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
  const digestLine = digests.map((group) => `${group.count} waiting for ${reviewActionLabel(group.action).toLowerCase()}`).join(" · ");

  return <section aria-labelledby="review-title" className="space-y-4" data-ui="email-review">
    <header className="space-y-3">
      <div className="flex flex-wrap items-end justify-between gap-2"><div><Title id="review-title" className="font-serif text-[26px] font-normal leading-none tracking-[-0.02em]">Review</Title><p className="mt-2 text-xs text-ink-secondary">A suggestion is a starting point. You decide what happens next.</p></div><p className="text-xs text-ink-tertiary tabular-nums" aria-live="polite">{visible.length} waiting{visible.length === items.length ? "" : ` of ${items.length}`}</p></div>
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line"><div role="group" aria-label="Filter by what is waiting" className="flex flex-wrap gap-x-4">{QUEUE_GATES.map((option) => <button key={option} type="button" aria-pressed={gate === option} onClick={() => onGateChange(option)} className="review-tab">{GATE_LABEL[option]}</button>)}</div><a href="#/watching" className="min-h-11 inline-flex items-center gap-1.5 text-xs text-ink-secondary">Watching only<ArrowUpRight size={13} aria-hidden="true" /></a></div>
    </header>

    {items.length === 0 ? <EmptyState title="Nothing needs your decision" description="New emails that need your review will appear here." icon={<Inbox className="h-6 w-6" aria-hidden="true" />} /> : visible.length === 0 ? <p className="border-t border-line py-6 text-sm text-ink-secondary">No emails match this filter.</p> : <>
      <div className="docket-briefing">
        <div><h2>Decision docket</h2><p>{digestLine}{digestLine ? " · " : ""}Each ticket is one decision. Nothing is sent until you review it.</p></div>
        <dl className="docket-stats"><div><dt>Waiting</dt><dd>{visible.length}</dd></div><div><dt>Already handled</dt><dd>{handledCount}</dd></div>{expiredCount > 0 && <div><dt>Expired</dt><dd>{expiredCount}</dd></div>}</dl>
      </div>
      <ol className="docket-list">{visible.map((item, index) => {
        const text = parseEmailText(item.summary);
        const handled = handledFor(item);
        const primary = index === 0 && selectedId === null;
        const open = () => onSelectItem?.(item);
        return <li key={item.id} data-selected={selectedId === item.id ? "true" : undefined} className={`docket-ticket${primary ? " is-next" : ""}`}>
          {primary ? <div className="docket-next">
            <div className="docket-next-main">
              <div className="docket-next-top"><span className="docket-chip">Next decision</span><span className="docket-gate">{gateLabel(item)}</span></div>
              <h3 className="docket-subject">{text.subject}</h3>
              <p className="docket-sender">{senderDisplay(item.sender_key)}</p>
              {text.preview && <p className="docket-preview">{text.preview}</p>}
            </div>
            <div className="docket-next-side">
              <p className="docket-recommend-label">{item.action === "ABSTAIN" ? "About this decision" : "Probation suggests"}</p>
              <p className="docket-recommend">{reviewActionLabel(item.action)}</p>
              {item.explanation.summary_reason && <p className="docket-reason">{item.explanation.summary_reason}</p>}
              <p className="docket-evidence">{handled ? `Compared with ${handled.count} recorded decisions.` : "No recorded precedent yet."}{item.audit_holdout ? " Spot check selected." : ""}</p>
              <Button variant="primary" size="md" aria-label="Review email" onClick={open}>Review email<ArrowRight size={15} aria-hidden="true" /></Button>
            </div>
          </div> : <div className="docket-row">
            <span className="docket-avatar" aria-hidden="true">{initial(item)}</span>
            <div className="min-w-0">
              <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1"><span className="docket-sender">{senderDisplay(item.sender_key)}</span><span className="docket-gate">{gateLabel(item)}</span></div>
              <h3 className="docket-subject">{text.subject}</h3>
              {text.preview && <p className="docket-preview">{text.preview}</p>}
              <p className="docket-meta">{reviewActionLabel(item.action)}{item.audit_holdout ? " · Spot check" : ""}{handled ? ` · From ${handled.count} recorded decisions` : ""}</p>
            </div>
            <Button variant="secondary" size="sm" aria-label="Review email" onClick={open}>Review email<ArrowUpRight size={14} aria-hidden="true" /></Button>
          </div>}
        </li>;
      })}</ol>
      {handledCount > 0 && <div className="docket-history"><p><strong>{handledCount} earlier decisions are already recorded.</strong> They are the history behind these permissions, not work on this list.</p><a href="#/permissions">See the evidence</a></div>}
      {expiredCount > 0 && <p className="text-xs text-ink-tertiary">{expiredCount} earlier items expired without a decision{expiredDigests.length ? ` across ${expiredDigests.length} task groups` : ""}.</p>}
    </>}
    <p className="text-xs text-ink-tertiary">Probation has not acted on any email in this list.</p>
  </section>;
}
