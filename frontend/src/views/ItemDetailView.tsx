import { useEffect } from "react";
import { ArrowLeft, Mail } from "lucide-react";
import { useItemRead } from "../api/queries";
import { QueueItem } from "../api/types";
import { reviewActionLabel, ReviewDecision, ReviewForm } from "../components/queue/ReviewForm";
import { VerificationCard } from "../components/queue/VerificationCard";
import { Button } from "../components/common/Button";
import { LinkButton } from "../components/common/LinkButton";
import { StatePanel } from "../components/common/StatePanel";
import { formatWhen, parseEmailText, senderDisplay } from "../lib/emailText";
interface ItemDetailViewProps {
  id: string; item?: QueueItem; authenticated: boolean; readOnly?: boolean;
  review: { busy: boolean; conflict: string | null; error: string | null; submit(proposalId: string, decision: ReviewDecision): Promise<string | null>; refresh(): void };
  onBack(): void;
}

const actionConsequence = (action: string): string =>
  ({
    ARCHIVE: "Removes it from Inbox. Undo for 7 days.",
    TRASH: "Moves it to Trash. Undo for 7 days.",
    REPLY: "Sends this reply. A sent message cannot be recalled.",
    FORWARD: "Forwards this email. A sent message cannot be recalled.",
    LEAVE: "Leaves the email unchanged.",
    ABSTAIN: "No action will be taken.",
  }[action] ?? "Probation records your decision before anything happens.");
export function ItemDetailView({ id, item, authenticated, readOnly = false, review, onBack }: ItemDetailViewProps) {
  const read = useItemRead(id, authenticated);
  const detail = read.data ?? null;
  const readError = read.error instanceof Error ? read.error.message : null;
  const readStatus = (read.error as { status?: number } | null)?.status;
  useEffect(() => { if (review.conflict !== null) void read.refetch(); }, [review.conflict]);
  const summary = item?.summary || detail?.summary || "Email details";
  const text = parseEmailText(summary);
  const action = detail?.action || item?.action || "";
  const supported = detail?.supported_actions ?? [];
  const draftText = detail?.draft?.body_text ?? item?.draft?.body_text ?? null;
  const needsInput = detail?.draft?.needs_user_input ?? item?.draft?.needs_user_input ?? false;
  const answered = detail?.user_response ?? null;
  const gateLabel = readOnly ? "Watching only" : (item?.gate ?? detail?.gate) === "SUGGEST" ? "Suggested for you" : "Needs your decision";
  const sender = detail?.sender_key || item?.sender_key;
  return <article className="space-y-5" data-ui="email-detail">
    <a href={readOnly ? "#/watching" : "#/queue"} onClick={(event) => { event.preventDefault(); onBack(); }} className="detail-back min-h-11 inline-flex items-center gap-2 text-sm text-ink-secondary"><ArrowLeft aria-hidden="true" size={15} />{readOnly ? "Back to watching" : "Back to review"}</a>
    <header className="space-y-3"><p className="text-xs text-ink-secondary">Email · {gateLabel}</p><h1 className="page-title break-words max-w-3xl">{text.subject}</h1><p className="text-sm text-ink-secondary">{action === "ABSTAIN" ? "Recommendation:" : "Requested action:"} <span className="text-ink">{reviewActionLabel(action)}</span></p><p className="text-xs leading-5 text-ink-tertiary">{actionConsequence(action)}</p></header>
    {readError !== null && <StatePanel state={readStatus === 401 || readStatus === 403 ? "locked" : "error"} title="Email details are unavailable" description={readError} onRetry={() => void read.refetch()} retryLabel="Try again" />}
    {read.isFetching && detail === null && readError === null && <p role="status" className="text-sm text-ink-secondary">Loading email details…</p>}
    {detail !== null && read.isStale && <p role="status" className="text-sm text-status-warning">This detail is out of date. A newer version may exist.</p>}
    {answered !== null && <p role="status" className="work-panel text-sm">You already answered this: {answered.response}. Nothing will be sent again.</p>}
    {review.conflict !== null && <div role="alert" aria-live="assertive" className="space-y-2 rounded-xl border border-status-warning/30 bg-status-warning/10 p-4"><p className="text-sm font-medium">Nothing was sent.</p><p className="text-sm text-ink-secondary">{review.conflict}</p><Button type="button" variant="secondary" size="md" onClick={review.refresh}>Review it again</Button></div>}
    {detail !== null && <div className="review-workspace">
      <div className="space-y-5">
        <section className="review-email" aria-labelledby="email-text-title"><div className="review-meta"><Mail size={18} aria-hidden="true" className="text-ink-tertiary" /><div className="min-w-0"><h2 id="email-text-title" className="text-sm font-semibold">Email text</h2><p className="mt-1 max-w-[42ch] truncate text-xs text-ink-tertiary">{senderDisplay(sender)}</p></div></div><div className="review-body">{text.body || text.preview || "The email body is unavailable."}</div>{text.disclaimer && <details className="mt-5 border-t border-line pt-4 text-xs leading-6 text-ink-tertiary"><summary className="min-h-11 cursor-pointer py-2 underline underline-offset-4">Sender disclaimer</summary><p className="max-w-[75ch] whitespace-pre-wrap">{text.disclaimer}</p></details>}</section>
        <ReviewForm formKey={id} proposedAction={action} supportedActions={supported} draftText={draftText} draftNeedsInput={needsInput} readOnly={readOnly || answered !== null} readOnlyNote={answered === null ? undefined : "Your decision is already recorded, so there is nothing left to confirm for this email."} busy={review.busy} conflict={null} onReview={(decision) => { void review.submit(id, decision); }} onFreshReview={review.refresh} />
        {readOnly && answered === null && supported.length > 0 && <div className="space-y-2"><LinkButton href={`#/queue/${encodeURIComponent(id)}`} variant="secondary" size="md">Choose an action yourself</LinkButton><p className="text-xs leading-5 text-ink-secondary">Review one exact action. This does not grant automatic permission.</p></div>}
      </div>
      <aside className="space-y-6 border-t border-line pt-6" aria-label="Suggestion evidence">
        <section aria-labelledby="why-title" className="space-y-3"><h2 id="why-title" className="section-heading">{action === "ABSTAIN" ? "About this decision" : "Why Probation suggested this"}</h2>
          {detail.explanation.summary_reason && <p className="section-caption">{detail.explanation.summary_reason}</p>}
          {detail.explanation.top_clues.length > 0 ? <ul className="space-y-3 text-sm text-ink-secondary">{detail.explanation.top_clues.map((clue,index) => <li key={`${clue}-${index}`} className="pl-3 border-l border-line">{clue}</li>)}</ul> : <p className="section-caption">{action === "ABSTAIN" ? "Probation has not suggested an action for this email." : "No explanation is available for this suggestion."}</p>}
          <p className="text-xs leading-5 text-ink-tertiary">The current permission is context for this kind of task, not approval for this email.</p>
          <details className="text-sm"><summary className="min-h-11 cursor-pointer py-3 text-ink underline underline-offset-4">Details</summary><div className="space-y-2 text-xs leading-5 text-ink-secondary"><p>Task: {detail.class_key || "unavailable"}</p><p>Evidence cutoff: {formatWhen(detail.verification_as_of ?? detail.proposed_at)}</p><p>Evidence line: {String(detail.evidence.k_strong ?? 0)} matching choices out of {String(detail.evidence.n_strong ?? 0)}.</p><p>Current permission: level {String(detail.licence.level ?? 0)}.</p>{detail.draft?.model_id && <p>Reply draft model: {detail.draft.model_id}</p>}<p>Web facts can only restrict, never widen, what Probation may do.</p></div></details>
        </section>
        <section aria-labelledby="similar-title" className="space-y-3"><h2 id="similar-title" className="section-heading">Similar decisions</h2>
          {detail.explanation.similar_cases.length > 0 ? <ul className="space-y-3 text-sm text-ink-secondary">{detail.explanation.similar_cases.slice(0, 3).map((past) => <li key={past.situation_id} className="space-y-1 rounded-lg border border-line bg-surface p-3"><p className="text-xs text-ink-tertiary">{Math.round((past.similarity <= 1 ? past.similarity * 100 : past.similarity))}% similar · {reviewActionLabel(past.action_taken)}</p><p className="text-sm">{parseEmailText(past.summary).subject || "Recorded decision"}</p></li>)}</ul> : <p className="section-caption">No similar recorded decisions are available for this email.</p>}
        </section>
        <VerificationCard card={detail.verification_card} asOf={detail.verification_as_of} />
      </aside>
    </div>}
    {detail === null && readError === null && !read.isLoading && <StatePanel state="empty" title="No detail for this email" description="Probation has no recorded detail for this item, so there is nothing to review." />}
  </article>;
}
