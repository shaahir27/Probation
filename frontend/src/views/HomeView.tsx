import { useState } from "react";
import { apiClient, newRequestId } from "../api/client";
import { ReplayStateResponse } from "../api/types";
import { LicenceItem, QueueItem } from "../api/types";
import { Button } from "../components/common/Button";
import { ArrowUpRight, Inbox } from "lucide-react";
import { LinkButton } from "../components/common/LinkButton";
import { StatePanel } from "../components/common/StatePanel";
import { parseEmailText, senderDisplay } from "../lib/emailText";

interface HomeViewProps {
  queueItems: QueueItem[];
  licences: LicenceItem[];
  profile: "private" | "synthetic";
  replay: ReplayStateResponse | null;
  replayError: string | null;
  onReplayRefresh(): void;
}

const levelName = (level: number) => ["Watching", "Suggests", "Acts with undo", "Acts automatically"][level] ?? "Unavailable";
const actionName = (action: string) =>
  ({ ARCHIVE: "Archive email", TRASH: "Move to trash", REPLY: "Send this reply", FORWARD: "Forward email", LEAVE: "Leave as is", ABSTAIN: "No recommendation yet" }[action] ??
    action.replace(/_/g, " ").toLowerCase());

/** Replay controls submit an intent and never claim the replay moved. */
function ReplayControls({ pending, setPending }: { pending: boolean; setPending(value: boolean): void }) {
  const [speed, setSpeed] = useState<1 | 10 | 100>(10);
  const [message, setMessage] = useState<string | null>(null);
  const send = async (kind: "start" | "pause" | "speed") => {
    setPending(true);
    setMessage(null);
    try {
      const requestId = newRequestId(`replay-${kind}`);
      if (kind === "start") await apiClient.startReplay(requestId);
      else if (kind === "pause") await apiClient.pauseReplay(requestId);
      else await apiClient.setReplaySpeed(speed, requestId);
      setMessage("Request received. Probation is still processing it.");
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "Probation could not record the replay request.");
    } finally {
      setPending(false);
    }
  };
  return <section aria-labelledby="replay-title" className="home-section space-y-3">
    <h2 id="replay-title" className="section-heading">Demo replay</h2>
    <p className="section-caption max-w-xl">Replay runs on the synthetic history only. Probation records the request; it does not claim the clock moved.</p>
    <div className="space-y-2">
      <div className="flex flex-wrap gap-2">
        <Button variant="primary" size="md" disabled={pending} onClick={() => void send("start")}>Play replay</Button>
        <Button variant="secondary" size="md" disabled={pending} onClick={() => void send("pause")}>Pause replay</Button>
      </div>
      <div className="flex items-center gap-2">
        <label htmlFor="replay-speed" className="text-sm text-ink-secondary">Speed</label>
        <select id="replay-speed" value={speed} onChange={(event) => setSpeed(Number(event.target.value) as 1 | 10 | 100)} className="min-h-11 rounded-md border border-line bg-surface px-2 text-sm">
          <option value={1}>1x</option>
          <option value={10}>10x</option>
          <option value={100}>100x</option>
        </select>
        <Button variant="secondary" size="md" disabled={pending} onClick={() => void send("speed")}>Set speed</Button>
      </div>
    </div>
    {message !== null && <p role="status" aria-live="polite" className="text-sm text-ink-secondary">{message}</p>}
  </section>;
}

export function HomeView({ queueItems, licences, profile, replay, replayError, onReplayRefresh }: HomeViewProps) {
  const [replayPending, setReplayPending] = useState(false);
  const needsDecision = queueItems.filter((item) => item.gate === "ASK").length;
  const suggested = queueItems.filter((item) => item.gate === "SUGGEST").length;
  const nextEmail = queueItems[0];
  const nextText = nextEmail ? parseEmailText(nextEmail.summary) : null;
  const permissionRows = licences
    .filter((entry) => entry.level > 0)
    .filter((entry, index, all) =>
      all.findIndex((other) => (other.title || other.action) === (entry.title || entry.action) && other.level === entry.level) === index,
    )
    .slice(0, 3);
  return <div className="space-y-8" data-ui="email-overview">
    <header className="flex flex-wrap items-end justify-between gap-4">
      <div><h1 className="page-title">Email overview</h1><p className="mt-3 text-sm text-ink-secondary">A second opinion on your inbox. Every decision stays yours.</p></div>
      <div className="flex items-center gap-4"><p className="text-sm text-ink-tertiary tabular-nums">{queueItems.length} waiting</p>{profile === "synthetic" && <span className="text-xs text-ink-tertiary">Synthetic replay</span>}</div>
    </header>

    <div className="overview-grid">
      <section className="overview-main" aria-labelledby="next-decision-title">
        <div className="flex items-center justify-between gap-3"><h2 id="next-decision-title" className="section-heading">Your review desk</h2><Inbox size={18} aria-hidden="true" className="text-ink-tertiary" /></div>
        <div className="decision-strip mt-5">
          <div><span>Waiting for you</span><strong>{queueItems.length}</strong></div>
          <div><span>Needs a decision</span><strong>{needsDecision}</strong></div>
          <div><span>Suggested</span><strong>{suggested}</strong></div>
        </div>

        {nextEmail && nextText ? <section className="home-section mt-7 space-y-3">
          <p className="inline-flex items-center gap-2 text-xs font-semibold text-brand"><span aria-hidden="true" className="h-1.5 w-1.5 rounded-full bg-accent ring-1 ring-ink" />Next to review</p>
          <h3 className="max-w-2xl font-serif text-[clamp(1.55rem,1.25rem+1vw,2rem)] font-normal leading-[1.2] tracking-[-0.02em] break-words">{nextText.subject}</h3>
          {nextText.preview && <p className="max-w-2xl text-sm leading-6 text-ink-secondary line-clamp-3">{nextText.preview}</p>}
          <p className="max-w-[34ch] truncate text-xs text-ink-tertiary">{senderDisplay(nextEmail.sender_key)}</p>
          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line pt-4">
            <div><p className="text-xs text-ink-secondary">Probation suggests</p><p className="mt-1 text-sm font-semibold">{actionName(nextEmail.action)}</p></div>
            <LinkButton href={`#/queue/${encodeURIComponent(nextEmail.id)}`} variant="primary" size="md">Review email<ArrowUpRight size={16} aria-hidden="true" /></LinkButton>
          </div>
        </section> : <div className="flex flex-col items-start justify-center space-y-3 border-t border-line py-10">
          <h3 className="font-serif text-2xl tracking-[-0.02em]">Nothing needs your decision</h3>
          <p className="section-caption max-w-md">New suggestions will appear here after a selected email has been processed. An empty desk never means an email was handled for you.</p>
          <LinkButton href="#/queue" variant="secondary" size="md">Open review<ArrowUpRight size={16} aria-hidden="true" /></LinkButton>
        </div>}

        {queueItems.length > 1 && <section className="home-section mt-6" aria-labelledby="also-waiting-title">
          <div className="mb-2 flex items-center justify-between gap-3"><h2 id="also-waiting-title" className="section-heading">Also waiting for you</h2><a href="#/queue" className="min-h-11 inline-flex items-center text-xs underline underline-offset-4">View all</a></div>
          <ul>{queueItems.slice(1, 4).map((item) => {
            const text = parseEmailText(item.summary);
            return <li key={item.id} className="border-b border-line last:border-0"><a href={`#/queue/${encodeURIComponent(item.id)}`} className="flex min-h-11 items-center gap-3 py-3.5"><span className="mail-identity" aria-hidden="true">{(item.sender_key || "E").charAt(0).toUpperCase()}</span><span className="min-w-0 flex-1"><span className="block truncate font-serif text-[16px] leading-[1.35] tracking-[-0.01em] text-ink">{text.subject}</span><span className="mt-0.5 block text-xs text-ink-tertiary">{actionName(item.action)}</span></span><ArrowUpRight size={15} aria-hidden="true" className="shrink-0 text-ink-tertiary" /></a></li>;
          })}</ul>
        </section>}

        <div className="home-section mt-6 flex flex-wrap items-center justify-between gap-3 text-xs text-ink-secondary"><span>Nothing in Review has been acted on.</span><a href="#/watching" className="min-h-11 inline-flex items-center gap-1 underline underline-offset-4">See what Probation is watching<ArrowUpRight size={13} aria-hidden="true" /></a></div>
      </section>

      <aside className="overview-next space-y-8" aria-label="Workspace context">
        <section className="home-rail" aria-labelledby="permissions-summary">
          <div className="mb-3 flex items-center justify-between gap-3"><h2 id="permissions-summary" className="section-heading">What Probation may do</h2></div>
          {permissionRows.length ? <ul className="divide-y divide-line">{permissionRows.map((entry) => <li key={`${entry.class_key}-${entry.action}`} className="py-3 first:pt-0"><p className="text-sm font-medium">{entry.title || actionName(entry.action)}</p><p className="mt-1 text-xs text-ink-secondary">{levelName(entry.level)}</p></li>)}</ul> : <p className="section-caption">No permissions yet. Probation starts by watching and earns each kind of permission from evidence.</p>}
          <div className="flex flex-wrap gap-x-4"><a href="#/permissions" className="mt-2 inline-flex min-h-11 items-center gap-2 text-sm text-ink underline underline-offset-4">See all permissions<ArrowUpRight size={14} aria-hidden="true" /></a><a href="#/more/insights" className="mt-2 inline-flex min-h-11 items-center gap-2 text-sm text-ink underline underline-offset-4">See performance<ArrowUpRight size={14} aria-hidden="true" /></a></div>
        </section>

        <section className="home-rail" aria-labelledby="readiness-title">
          <h2 id="readiness-title" className="section-heading mb-3">Workspace clock</h2>
          {replay === null ? replayError !== null ? <StatePanel state="error" title="Clock state unavailable" description={replayError} onRetry={onReplayRefresh} /> : <p role="status" className="section-caption">Checking the clock state…</p> : !replay.available ? <p className="section-caption">Replay state is unavailable. Probation is not acting on replay time.</p> : <div className="space-y-2"><p className="text-sm">{replay.mode === "replay" ? "Synthetic replay" : "Live clock"}</p><p className="text-xs text-ink-secondary">{replay.mode === "replay" ? (replay.simulated_date ? `Date shown: ${replay.simulated_date.split("T")[0]}` : "No date recorded") : "Mailbox time follows the live clock."}{replay.mode === "replay" ? ` · ${replay.speed}x · ${replay.running ? "Running" : "Paused"}` : ""}</p></div>}
          <a href="#/more/connections" className="mt-3 inline-flex min-h-11 items-center gap-1 text-sm underline underline-offset-4">Connection details<ArrowUpRight size={14} aria-hidden="true" /></a>
        </section>
        <ReplayControls pending={replayPending} setPending={setReplayPending} />
      </aside>
    </div>
  </div>;
}
