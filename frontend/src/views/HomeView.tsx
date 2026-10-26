import { useState } from "react";
import { apiClient, newRequestId } from "../api/client";
import { ReplayStateResponse } from "../api/types";
import { LicenceItem, QueueItem } from "../api/types";
import { Button } from "../components/common/Button";
import { ArrowUpRight, Inbox } from "lucide-react";
import { LinkButton } from "../components/common/LinkButton";
import { StatePanel } from "../components/common/StatePanel";

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
  return (
    <section aria-labelledby="replay-title" className="space-y-2 border-t border-line pt-5">
      <h2 id="replay-title" className="text-base font-medium">
        Demo replay
      </h2>
      <p className="text-sm text-ink-secondary">
        Replay runs on the synthetic history only. Probation records the request; it does not claim the clock moved.
      </p>
      <div className="flex flex-wrap items-center gap-2">
        <Button variant="primary" size="md" disabled={pending} onClick={() => void send("start")}>
          Play replay
        </Button>
        <Button variant="secondary" size="md" disabled={pending} onClick={() => void send("pause")}>
          Pause replay
        </Button>
        <label htmlFor="replay-speed" className="text-sm text-ink-secondary">
          Speed
        </label>
        <select
          id="replay-speed"
          value={speed}
          onChange={(event) => setSpeed(Number(event.target.value) as 1 | 10 | 100)}
          className="min-h-11 rounded-md border border-line bg-surface px-2 text-sm"
        >
          <option value={1}>1x</option>
          <option value={10}>10x</option>
          <option value={100}>100x</option>
        </select>
        <Button variant="secondary" size="md" disabled={pending} onClick={() => void send("speed")}>
          Set speed
        </Button>
      </div>
      {message !== null && (
        <p role="status" aria-live="polite" className="text-sm text-ink-secondary">
          {message}
        </p>
      )}
    </section>
  );
}

export function HomeView({ queueItems, licences, profile, replay, replayError, onReplayRefresh }: HomeViewProps) {
  const [replayPending, setReplayPending] = useState(false);
  const needsDecision = queueItems.filter((item) => item.gate === "ASK").length;
  const suggested = queueItems.filter((item) => item.gate === "SUGGEST").length;
  const nextEmail = queueItems[0];
  return <div className="space-y-7" data-ui="email-overview">
    <header className="flex flex-wrap items-end justify-between gap-4">
      <div><h1 className="font-serif text-[28px] font-normal tracking-tight">Email overview</h1><p className="mt-2 text-sm text-ink-secondary">A second opinion on your inbox. Every decision stays yours.</p></div>
      <span className="text-xs text-ink-secondary">{profile === "synthetic" ? "Public synthetic replay" : "Private test account"}</span>
    </header>
    <div className="overview-grid">
      <section className="work-panel overview-main" aria-labelledby="next-decision-title">
        <div className="flex items-center justify-between gap-3"><h2 id="next-decision-title" className="section-heading">Your review desk</h2><Inbox size={18} aria-hidden="true" className="text-ink-tertiary" /></div>
        <div className="my-6 decision-strip">
          <div><span>Waiting for you</span><strong>{queueItems.length}</strong></div>
          <div><span>Needs a decision</span><strong>{needsDecision}</strong></div>
          <div><span>Suggested</span><strong>{suggested}</strong></div>
        </div>
        {nextEmail ? <div className="space-y-4 pb-3">
          <p className="text-xs text-brand">Next to review</p>
          <h3 className="text-lg font-medium leading-7 break-words line-clamp-3">{nextEmail.summary || "Email details are unavailable."}</h3>
          <p className="text-sm text-ink-secondary">{nextEmail.sender_key || "Sender unavailable"}</p>
          <div className="work-panel-soft flex flex-wrap items-center justify-between gap-3"><div><p className="text-xs text-ink-secondary mb-1">Probation suggests</p><p className="text-sm font-medium">{actionName(nextEmail.action)}</p></div><LinkButton href={`#/queue/${encodeURIComponent(nextEmail.id)}`} variant="primary" size="md">Review email<ArrowUpRight size={16} aria-hidden="true" /></LinkButton></div>
        </div> : <div className="flex-1 flex flex-col items-start justify-center py-7 space-y-3">
          <h3 className="font-serif text-2xl">Nothing needs your decision</h3>
          <p className="section-caption max-w-md">New suggestions will appear here after a selected email has been processed. An empty desk never means an email was handled for you.</p>
          <LinkButton href="#/queue" variant="secondary" size="md">Open review<ArrowUpRight size={16} aria-hidden="true" /></LinkButton>
        </div>}
        <div className="mt-5 pt-5 border-t border-line flex flex-wrap items-center justify-between gap-3 text-xs text-ink-secondary"><span>Nothing in Review has been acted on.</span><a href="#/watching" className="min-h-11 inline-flex items-center gap-1 underline underline-offset-4">See what Probation is watching<ArrowUpRight size={13} aria-hidden="true" /></a></div>
      </section>
      <div className="overview-next">
        <section className="work-panel" aria-labelledby="permissions-summary"><div className="flex items-center justify-between gap-3 mb-4"><h2 id="permissions-summary" className="section-heading">What Probation may do</h2></div>
          {licences.length ? <ul className="divide-y divide-line">{licences.slice(0,3).map((entry) => <li key={`${entry.class_key}-${entry.action}`} className="py-3 first:pt-0"><p className="text-sm font-medium">{entry.title || actionName(entry.action)}</p><p className="mt-1 text-xs text-ink-secondary">{levelName(entry.level)}</p></li>)}</ul> : <p className="section-caption">No permissions yet. Probation starts by watching and earns each kind of permission from evidence.</p>}
          <div className="flex flex-wrap gap-x-4"><a href="#/permissions" className="inline-flex items-center gap-2 min-h-11 mt-3 text-sm text-ink underline underline-offset-4">See all permissions<ArrowUpRight size={14} aria-hidden="true" /></a><a href="#/more/insights" className="inline-flex items-center gap-2 min-h-11 mt-3 text-sm text-ink underline underline-offset-4">See performance<ArrowUpRight size={14} aria-hidden="true" /></a></div>
        </section>
        <section className="work-panel" aria-labelledby="readiness-title"><h2 id="readiness-title" className="section-heading mb-3">Workspace clock</h2>
          {replay === null ? replayError !== null ? <StatePanel state="error" title="Clock state unavailable" description={replayError} onRetry={onReplayRefresh} /> : <p role="status" className="section-caption">Checking the clock state…</p> : !replay.available ? <p className="section-caption">Replay state is unavailable. Probation is not acting on replay time.</p> : <div className="space-y-2"><p className="text-sm">{replay.mode === "replay" ? "Synthetic replay" : "Live clock"}</p><p className="text-xs text-ink-secondary">{replay.simulated_date ? `Date shown: ${replay.simulated_date.split("T")[0]}` : "No date recorded"}{replay.mode === "replay" ? ` · ${replay.speed}x · ${replay.running ? "Running" : "Paused"}` : ""}</p></div>}
          <a href="#/more/connections" className="min-h-11 inline-flex items-center gap-2 mt-3 text-sm text-ink underline underline-offset-4">Connection details<ArrowUpRight size={14} aria-hidden="true" /></a>
        </section>
      </div>
    </div>
    {queueItems.length > 1 && <section className="work-panel" aria-labelledby="also-waiting-title"><div className="flex items-center justify-between mb-5"><h2 id="also-waiting-title" className="section-heading">Also waiting for you</h2><a href="#/queue" className="min-h-11 inline-flex items-center text-xs underline underline-offset-4">View all</a></div><ul>{queueItems.slice(1,4).map((item) => <li key={item.id} className="mail-list-row"><span className="mail-identity" aria-hidden="true">{(item.sender_key || "E").charAt(0).toUpperCase()}</span><div className="min-w-0 flex-1"><a href={`#/queue/${encodeURIComponent(item.id)}`} className="min-h-11 inline-flex items-center text-sm font-medium leading-6 break-words">{item.summary || "Email details unavailable"}</a><p className="text-xs text-ink-secondary mt-1">{actionName(item.action)}</p></div><ArrowUpRight size={16} aria-hidden="true" className="shrink-0 text-ink-tertiary mt-3" /></li>)}</ul></section>}
    {profile === "synthetic" && <section className="work-panel"><ReplayControls pending={replayPending} setPending={setReplayPending} /></section>}
  </div>;
}
