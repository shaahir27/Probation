import { ActionItem, LicenceItem, QueueItem } from "../api/types";
import { ArrowUpRight, Inbox } from "lucide-react";
import { LinkButton } from "../components/common/LinkButton";
import { actionStatusLabel } from "../api/action_status";
import { apiClient } from "../api/client";
import { useRead } from "../api/queries";
import { parseEmailText, senderDisplay } from "../lib/emailText";

interface HomeViewProps {
  queueItems: QueueItem[];
  licences: LicenceItem[];
  actions: ActionItem[];
  profile: "private" | "synthetic";
}

const levelName = (level: number) => ["Watching", "Suggests", "Acts with undo", "Acts automatically"][level] ?? "Unavailable";
const actionName = (action: string) =>
  ({ ARCHIVE: "Archive email", TRASH: "Move to trash", REPLY: "Send this reply", FORWARD: "Forward email", LEAVE: "Leave as is", ABSTAIN: "No recommendation yet" }[action] ??
    action.replace(/_/g, " ").toLowerCase());

const LADDER = ["Watch", "Suggest", "Act with undo", "Act automatically"];

export function HomeView({ queueItems, licences, actions, profile }: HomeViewProps) {
  const gmailRead = useRead(["private", "gmail-setup"], (signal) => apiClient.getGmailSetup(signal), { enabled: profile === "private" });
  const gmailAction = useRead(["private", "gmail-write-setup"], (signal) => apiClient.getGmailWriteSetup(signal), { enabled: profile === "private" });
  const nextEmail = queueItems[0];
  const nextText = nextEmail ? parseEmailText(nextEmail.summary) : null;
  const currentLevel = licences.reduce((max, entry) => Math.max(max, entry.level), 0);
  const recent = actions.slice(0, 3);
  const readAccess = profile === "synthetic" ? "Synthetic demo" : gmailRead.isLoading ? "Checking…" : gmailRead.data?.connected ? "Connected" : "Not connected";
  const actionAccess = profile === "synthetic" ? "Synthetic demo" : gmailAction.isLoading ? "Checking…" : gmailAction.data?.connected ? "Granted" : "Not granted";

  return <div className="space-y-10" data-ui="workspace-overview">
    <header className="flex flex-wrap items-end justify-between gap-5">
      <div className="max-w-2xl">
        <h1 className="page-title">Workspace overview</h1>
        <p className="mt-3 text-sm leading-6 text-ink-secondary">Probation watches the apps you connect, explains what it would do, and waits for your permission. You stay in control of every action.</p>
      </div>
      <LinkButton href="#/more/connections" variant="secondary" size="md">Manage access<ArrowUpRight size={15} aria-hidden="true" /></LinkButton>
    </header>

    <section className="grid min-w-0 gap-6 border-y border-line py-5 sm:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)_auto] sm:items-center" aria-labelledby="access-summary-title">
      <div className="flex min-w-0 items-center gap-4">
        <img src="/integrations/gmail.webp" alt="" width="40" height="40" className="shrink-0 object-contain" />
        <div className="min-w-0"><h2 id="access-summary-title" className="section-heading">Gmail</h2><p className="mt-1 text-xs text-ink-secondary">Email is the first connected app. Calendar and Drive are planned.</p></div>
      </div>
      <div className="grid min-w-0 grid-cols-2 gap-5 text-sm">
        <div className="min-w-0"><p className="text-xs text-ink-tertiary">Read access</p><p className="mt-1 font-medium">{readAccess}</p></div>
        <div className="min-w-0"><p className="text-xs text-ink-tertiary">Action access</p><p className="mt-1 font-medium">{actionAccess}</p></div>
      </div>
      <a href="#/more/connections" className="min-h-11 shrink-0 inline-flex items-center gap-1 text-sm underline underline-offset-4">Change access<ArrowUpRight size={14} aria-hidden="true" /></a>
    </section>

    <div className="grid min-w-0 gap-10 lg:grid-cols-[minmax(0,1.55fr)_minmax(280px,1fr)] lg:items-start [&>*]:min-w-0">
      <section className="home-section min-w-0" aria-labelledby="review-desk-title">
        <div className="flex flex-wrap items-baseline justify-between gap-3">
          <h2 id="review-desk-title" className="section-heading">Your review desk</h2>
          <p className="text-sm text-ink-tertiary"><span>Waiting for you</span> <strong className="ml-1 font-serif text-xl font-normal text-ink">{queueItems.length}</strong></p>
        </div>

        {nextEmail && nextText ? <div className="mt-7 space-y-4">
          <p className="inline-flex items-center gap-2 text-xs font-semibold text-brand"><span aria-hidden="true" className="h-1.5 w-1.5 rounded-full bg-accent ring-1 ring-ink" />Next to review</p>
          <h3 className="max-w-2xl font-serif text-[clamp(1.7rem,1.3rem+1.2vw,2.35rem)] font-normal leading-[1.18] tracking-[-0.025em] break-words">{nextText.subject}</h3>
          {nextText.preview && <p className="max-w-2xl text-sm leading-6 text-ink-secondary line-clamp-3">{nextText.preview}</p>}
          <p className="max-w-[36ch] truncate text-xs text-ink-tertiary">{senderDisplay(nextEmail.sender_key)}</p>
          <div className="flex flex-wrap items-center justify-between gap-4 border-t border-line pt-5">
            <div><p className="text-xs text-ink-secondary">Probation suggests</p><p className="mt-1 text-sm font-semibold">{actionName(nextEmail.action)}</p></div>
            <LinkButton href={`#/queue/${encodeURIComponent(nextEmail.id)}`} variant="primary" size="md">Review email<ArrowUpRight size={16} aria-hidden="true" /></LinkButton>
          </div>
        </div> : <div className="flex flex-col items-start space-y-3 py-10">
          <Inbox size={24} aria-hidden="true" className="text-ink-tertiary" />
          <h3 className="font-serif text-2xl tracking-[-0.02em]">Nothing needs your decision</h3>
          <p className="section-caption max-w-md">New suggestions appear here after a connected app has processed an item. An empty desk never means something was handled for you.</p>
          <LinkButton href="#/queue" variant="secondary" size="md">Open review<ArrowUpRight size={16} aria-hidden="true" /></LinkButton>
        </div>}

        {queueItems.length > 1 && <section className="home-section mt-8" aria-labelledby="also-waiting-title">
          <div className="mb-2 flex items-center justify-between gap-3"><h2 id="also-waiting-title" className="section-heading">Also waiting for you</h2><a href="#/queue" className="min-h-11 inline-flex items-center text-xs underline underline-offset-4">View all</a></div>
          <ul>{queueItems.slice(1, 4).map((item) => {
            const text = parseEmailText(item.summary);
            return <li key={item.id} className="border-b border-line last:border-0"><a href={`#/queue/${encodeURIComponent(item.id)}`} className="flex min-h-11 items-center gap-3 py-3.5"><span className="mail-identity" aria-hidden="true">{(item.sender_key || "E").charAt(0).toUpperCase()}</span><span className="min-w-0 flex-1"><span className="block truncate font-serif text-[16px] leading-[1.35] tracking-[-0.01em] text-ink">{text.subject}</span><span className="mt-0.5 block text-xs text-ink-tertiary">{actionName(item.action)}</span></span><ArrowUpRight size={15} aria-hidden="true" className="shrink-0 text-ink-tertiary" /></a></li>;
          })}</ul>
        </section>}

        <div className="mt-7 flex flex-wrap items-center justify-between gap-3 border-t border-line pt-4 text-xs text-ink-secondary"><span>Nothing in Review has been acted on.</span><a href="#/watching" className="min-h-11 inline-flex items-center gap-1 underline underline-offset-4">See what Probation is watching<ArrowUpRight size={13} aria-hidden="true" /></a></div>
      </section>

      <aside className="space-y-8" aria-label="Workspace context">
        <section className="home-rail" aria-labelledby="permission-ladder-title">
          <h2 id="permission-ladder-title" className="section-heading">How permission is earned</h2>
          <p className="mt-2 text-xs leading-5 text-ink-secondary">Every task type starts by watching. Probation only moves up when its own history proves it would have done what you did.</p>
          <ol className="mt-4 space-y-0">
            {LADDER.map((label, index) => <li key={label} className={`flex items-center justify-between border-b border-line py-3 text-sm last:border-0 ${index === currentLevel ? "font-semibold text-ink" : "text-ink-secondary"}`}><span>{label}</span><span className="text-xs text-ink-tertiary">{index === currentLevel ? "You are here" : levelName(index)}</span></li>)}
          </ol>
          <div className="mt-4 flex flex-wrap gap-x-4"><a href="#/permissions" className="inline-flex min-h-11 items-center gap-1 text-sm underline underline-offset-4">All permissions<ArrowUpRight size={14} aria-hidden="true" /></a><a href="#/more/insights" className="inline-flex min-h-11 items-center gap-1 text-sm underline underline-offset-4">Performance<ArrowUpRight size={14} aria-hidden="true" /></a></div>
        </section>

        <section className="home-rail" aria-labelledby="recent-activity-title">
          <div className="flex items-center justify-between gap-3"><h2 id="recent-activity-title" className="section-heading">Recent activity</h2><a href="#/actions" className="min-h-11 inline-flex items-center text-xs underline underline-offset-4">All activity</a></div>
          {recent.length ? <ul className="mt-3 divide-y divide-line">{recent.map((action) => {
            const text = parseEmailText(action.summary);
            return <li key={action.id} className="py-3 first:pt-0"><p className="line-clamp-1 font-serif text-[16px] leading-[1.35] tracking-[-0.01em] text-ink">{text.subject}</p><p className="mt-1 text-xs text-ink-tertiary">{actionStatusLabel(action.status)} · {action.type.replace(/_/g, " ").toLowerCase()}</p></li>;
          })}</ul> : <p className="mt-3 text-sm text-ink-secondary">No actions yet. Probation has nothing to report, which is different from an action being completed.</p>}
        </section>

        <section className="home-rail" aria-labelledby="workspace-note-title">
          <h2 id="workspace-note-title" className="section-heading">Workspace</h2>
          <p className="mt-2 text-sm leading-6 text-ink-secondary">{profile === "synthetic" ? "Synthetic workspace. Replaying recorded history without touching a real account." : "Private workspace. Connected apps are local, and every decision stays yours."}</p>
          <a href="#/more/settings" className="mt-2 inline-flex min-h-11 items-center gap-1 text-sm underline underline-offset-4">Settings in use<ArrowUpRight size={14} aria-hidden="true" /></a>
        </section>
      </aside>
    </div>
  </div>;
}
