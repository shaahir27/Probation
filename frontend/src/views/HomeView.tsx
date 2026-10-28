import { ActionItem, LicenceItem, QueueItem } from "../api/types";
import { ArrowRight, ArrowUpRight, Inbox } from "lucide-react";
import { LinkButton } from "../components/common/LinkButton";
import { actionStatusLabel, isUnconfirmedResult, RESULT_NOT_CONFIRMED } from "../api/action_status";
import { apiClient } from "../api/client";
import { useRead } from "../api/queries";
import { parseEmailText, senderDisplay } from "../lib/emailText";

interface HomeViewProps {
  queueItems: QueueItem[];
  licences: LicenceItem[];
  actions: ActionItem[];
  profile: "private" | "synthetic";
}

const actionName = (action: string) =>
  ({ ARCHIVE: "Archive email", TRASH: "Move to trash", REPLY: "Send this reply", FORWARD: "Forward email", LEAVE: "Leave as is", ABSTAIN: "No recommendation yet" }[action] ??
    action.replace(/_/g, " ").toLowerCase());

export function HomeView({ queueItems, actions, profile }: HomeViewProps) {
  const gmailRead = useRead(["private", "gmail-setup"], (signal) => apiClient.getGmailSetup(signal), { enabled: profile === "private" });
  const gmailAction = useRead(["private", "gmail-write-setup"], (signal) => apiClient.getGmailWriteSetup(signal), { enabled: profile === "private" });
  const nextEmail = queueItems[0];
  const nextText = nextEmail ? parseEmailText(nextEmail.summary) : null;
  const readAccess = profile === "synthetic" ? "Synthetic demo" : gmailRead.isLoading ? "Checking…" : gmailRead.error ? "Unavailable" : gmailRead.data?.connected ? "Connected" : "Not connected";
  const actionAccess = profile === "synthetic" ? "Synthetic demo" : gmailAction.isLoading ? "Checking…" : gmailAction.error ? "Unavailable" : gmailAction.data?.connected ? "Granted" : "Not granted";

  return <div className="dashboard" data-ui="workspace-overview">
    <header className="dashboard-heading">
      <div><p className="dashboard-eyebrow">Your workspace</p><h1 className="page-title">Workspace overview</h1>
        <p className="dashboard-intro">Your review desk, recent activity, and the permissions behind each decision.</p></div>
      <LinkButton href="#/more/connections" variant="secondary" size="md">Manage access<ArrowUpRight size={15} aria-hidden="true" /></LinkButton>
    </header>

    <section className="dashboard-access" aria-labelledby="access-summary-title">
      <div className="dashboard-access-app"><img src="/integrations/gmail.webp" alt="" width="32" height="32" /><div><h2 id="access-summary-title">Gmail</h2><p>Calendar and Drive are planned</p></div></div>
      <dl className="dashboard-access-status"><div><dt>Read access</dt><dd>{readAccess}</dd></div><div><dt>Action access</dt><dd>{actionAccess}</dd></div></dl>
      <a href="#/more/connections">Change access <ArrowUpRight size={14} aria-hidden="true" /></a>
    </section>

    <div className="dashboard-grid">
      <div className="dashboard-main">
        <section className="dashboard-panel" aria-labelledby="review-desk-title">
          <div className="dashboard-panel-header"><div><p className="dashboard-eyebrow">Needs your attention</p><h2 id="review-desk-title">Your review desk</h2></div><span className="dashboard-count">{queueItems.length} waiting</span></div>
          {nextEmail && nextText ? <div className="dashboard-review">
            <p className="dashboard-label">Next to review</p>
            <h3>{nextText.subject}</h3>
            <p className="dashboard-sender">{senderDisplay(nextEmail.sender_key)}</p>
            {nextText.preview && <p className="dashboard-preview">{nextText.preview}</p>}
            <div className="dashboard-decision"><div><p className="dashboard-label">{nextEmail.action === "ABSTAIN" ? "Recommendation" : "Probation suggests"}</p><p>{actionName(nextEmail.action)}</p></div><LinkButton href={`#/queue/${encodeURIComponent(nextEmail.id)}`} variant="primary" size="md">Review email<ArrowRight size={16} aria-hidden="true" /></LinkButton></div>
          </div> : <div className="dashboard-empty"><Inbox size={22} aria-hidden="true" /><div><h3>Nothing needs your decision</h3><p>New items will appear here when they need your attention.</p><LinkButton href="#/queue" variant="secondary" size="md">Open review<ArrowRight size={16} aria-hidden="true" /></LinkButton></div></div>}
          {queueItems.length > 1 && <div className="dashboard-more"><span>{queueItems.length - 1} more waiting for review</span><a href="#/queue">View all <ArrowUpRight size={14} aria-hidden="true" /></a></div>}
          <div className="dashboard-panel-footer"><span>Nothing in Review has been acted on.</span><a href="#/watching">See what Probation is watching <ArrowUpRight size={14} aria-hidden="true" /></a></div>
        </section>

        <section className="dashboard-panel dashboard-activity" aria-labelledby="recent-activity-title">
          <div className="dashboard-panel-header"><div><p className="dashboard-eyebrow">Recorded actions</p><h2 id="recent-activity-title">Recent activity</h2></div><a href="#/actions">All activity <ArrowUpRight size={14} aria-hidden="true" /></a></div>
          {actions.length ? <ul>{actions.slice(0, 3).map((action) => {
            const text = parseEmailText(action.summary);
            const status = isUnconfirmedResult(action.status) || isUnconfirmedResult(action.execution_status) ? RESULT_NOT_CONFIRMED : actionStatusLabel(action.status);
            return <li key={action.id}><span className="dashboard-activity-subject">{text.subject || action.type.replace(/_/g, " ").toLowerCase()}</span><span className="dashboard-activity-status">{status} · {action.type.replace(/_/g, " ").toLowerCase()}</span></li>;
          })}</ul> : <p className="dashboard-no-activity">No actions have been recorded yet.</p>}
        </section>
      </div>

      <aside className="dashboard-side" aria-label="Workspace context">
        <section className="dashboard-panel dashboard-permissions" aria-labelledby="permission-ladder-title">
          <p className="dashboard-eyebrow">Evidence before action</p><h2 id="permission-ladder-title">How permission is earned</h2>
          <p className="dashboard-side-copy">Each task and action has its own permission, based on the evidence available.</p>
          <ol>{["Watch", "Suggest", "Act with undo", "Act automatically"].map((label, index) => <li key={label}><span>{index + 1}</span>{label}</li>)}</ol>
          <p className="dashboard-side-copy">See your current permissions for each task.</p>
          <div className="dashboard-side-links"><a href="#/permissions">All permissions <ArrowUpRight size={14} aria-hidden="true" /></a><a href="#/more/insights">Performance <ArrowUpRight size={14} aria-hidden="true" /></a></div>
        </section>
        <section className="dashboard-workspace" aria-labelledby="workspace-note-title"><h2 id="workspace-note-title">Workspace</h2><p>{profile === "synthetic" ? "Synthetic workspace. Fictional data is kept separate from connected accounts." : "Private workspace. Connected apps use the access you granted."}</p><a href="#/more/settings">Settings in use <ArrowUpRight size={14} aria-hidden="true" /></a></section>
      </aside>
    </div>
  </div>;
}
