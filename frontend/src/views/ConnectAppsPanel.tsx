import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { apiClient, type GmailSetupStatus } from "../api/client";
import { useRead } from "../api/queries";
import { Button } from "../components/common/Button";

const APPS = [
  { id: "gmail", name: "Gmail", description: "Turn incoming email into suggestions you can review.", available: true },
  { id: "calendar", name: "Google Calendar", description: "Invitations and scheduling, with permission earned per task.", available: false },
  { id: "drive", name: "Google Drive", description: "Organise files with a clear record of every decision.", available: false },
];

const SETUP_REASON_COPY: Record<string, string> = {
  readonly_setup_not_completed:
    "Google sign-in did not finish. Use the configured test account and approve access within the setup window.",
  readonly_setup_launch_failed: "Probation could not start the local Google setup process.",
  readonly_setup_already_running: "A Google setup attempt is already open. Finish it or wait for it to close.",
  readonly_registration_unavailable: "The Google registration could not be verified.",
  readonly_grant_not_configured: "Gmail read access is not connected yet.",
  write_grant_not_configured: "Gmail action access is not granted yet.",
  setup_status_unavailable: "The connection attempt could not be confirmed.",
  private_profile_required: "Real accounts are connected only in the private app.",
};

const CONNECTION_STATE_COPY: Record<string, string> = {
  ACTIVE: "Active",
  PAUSED: "Paused",
  DISCONNECTED: "Disconnected",
  AUTH_REQUIRED: "Needs sign-in",
  SHADOW: "Connected",
};

type SetupKind = "read" | "write";
type CommandKind = "pause" | "resume" | "disconnect";

function useGmailSetupFlow(kind: SetupKind, enabled: boolean) {
  const queryClient = useQueryClient();
  const initial = useRead(
    ["private", kind === "read" ? "gmail-setup" : "gmail-write-setup"],
    (signal) => (kind === "read" ? apiClient.getGmailSetup(signal) : apiClient.getGmailWriteSetup(signal)),
    { enabled },
  );
  const [requestId, setRequestId] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [outcome, setOutcome] = useState<"succeeded" | "failed" | "unknown" | null>(null);
  const [last, setLast] = useState<GmailSetupStatus | null>(null);
  const progress = useRead(
    ["private", `gmail-${kind}-setup`, requestId ?? "none"],
    (signal) =>
      kind === "read"
        ? apiClient.getGmailSetupRequest(requestId!, signal)
        : apiClient.getGmailWriteSetupRequest(requestId!, signal),
    { enabled: enabled && requestId !== null, refetchInterval: requestId === null ? false : 1500 },
  );

  useEffect(() => {
    const value = progress.data;
    if (!value) return;
    setLast(value);
    if (value.status === "succeeded") {
      setOutcome("succeeded");
      setRequestId(null);
      void queryClient.invalidateQueries({ queryKey: ["private", "gmail-connections"] });
      void queryClient.invalidateQueries({ queryKey: ["private", "gmail-setup"] });
      void queryClient.invalidateQueries({ queryKey: ["private", "gmail-write-setup"] });
    } else if (value.status === "failed" || value.status === "unknown") {
      setOutcome(value.status);
      setRequestId(null);
    }
  }, [progress.data, queryClient]);

  async function start(): Promise<void> {
    setStarting(true);
    setError(null);
    setOutcome(null);
    const id = `gmail-${kind}-${crypto.randomUUID()}`;
    try {
      const result = kind === "read"
        ? await apiClient.startGmailSetup(id)
        : await apiClient.startGmailWriteSetup(id);
      setLast(result);
      if (result.status === "succeeded") {
        setOutcome("succeeded");
        void queryClient.invalidateQueries({ queryKey: ["private", "gmail-connections"] });
        void queryClient.invalidateQueries({ queryKey: ["private", "gmail-setup"] });
        void queryClient.invalidateQueries({ queryKey: ["private", "gmail-write-setup"] });
      } else if (result.status === "failed") {
        setOutcome("failed");
      } else {
        setRequestId(id);
      }
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not start Google connection.");
    } finally {
      setStarting(false);
    }
  }

  return { initial, last, outcome, error, pending: starting || requestId !== null, start };
}

export function ConnectAppsPanel({ profile }: { profile: "private" | "synthetic" | null }) {
  const isPrivate = profile === "private";
  const queryClient = useQueryClient();
  const readFlow = useGmailSetupFlow("read", isPrivate);
  const connections = useRead(
    ["private", "gmail-connections"],
    (signal) => apiClient.getGmailConnections(signal),
    { enabled: isPrivate },
  );
  const connection = connections.data?.connections[0] ?? null;
  const connectionState = connection?.state ?? null;
  const [accessClosed, setAccessClosed] = useState(false);
  const readConnected =
    !accessClosed &&
    connectionState !== "DISCONNECTED" &&
    connectionState !== "AUTH_REQUIRED" &&
    readFlow.initial.data?.connected === true;
  const writeFlow = useGmailSetupFlow("write", isPrivate && readConnected);
  const writeConnected = writeFlow.initial.data?.connected === true;
  const accessLoading = readFlow.initial.isLoading || connections.isLoading;
  const [confirmDisconnect, setConfirmDisconnect] = useState(false);
  const [fullConnect, setFullConnect] = useState(false);
  const [command, setCommand] = useState<{ id: string; kind: CommandKind } | null>(null);
  const [commandNotice, setCommandNotice] = useState<string | null>(null);
  const [commandError, setCommandError] = useState<string | null>(null);
  const commandStatus = useRead(
    ["private", "gmail-command", command?.id ?? "none"],
    (signal) => apiClient.getGmailLifecycleStatus(command!.id, signal),
    { enabled: isPrivate && command !== null, refetchInterval: command === null ? false : 1500 },
  );

  useEffect(() => {
    const status = commandStatus.data?.status;
    if (status === "succeeded" && command !== null) {
      setCommandNotice(
        command.kind === "pause"
          ? "Access paused. Probation will not read or act until you resume."
          : command.kind === "resume"
            ? "Access resumed for this connection."
            : "Gmail is disconnected. No further email will be read or acted on.",
      );
      if (command.kind === "disconnect") setAccessClosed(true);
      setCommand(null);
      void connections.refetch();
      void readFlow.initial.refetch();
      void writeFlow.initial.refetch();
      void queryClient.invalidateQueries({ queryKey: ["private", "gmail-connections"] });
      void queryClient.invalidateQueries({ queryKey: ["private", "gmail-setup"] });
      void queryClient.invalidateQueries({ queryKey: ["private", "gmail-write-setup"] });
    } else if (status === "failed" && command !== null) {
      setCommandError("Probation could not update access. Nothing else changed.");
      setCommand(null);
    }
  }, [command, commandStatus.data?.status, queryClient]);

  useEffect(() => {
    if (commandStatus.error instanceof Error && command !== null) {
      setCommandError(commandStatus.error.message);
      setCommand(null);
    }
  }, [command, commandStatus.error]);

  useEffect(() => {
    // A combined choice asks for read first, then the action consent. Two Google prompts are
    // deliberate: the observer keeps its own read-only credential.
    if (fullConnect && !readFlow.pending && (readFlow.error || readFlow.outcome === "failed" || readFlow.outcome === "unknown")) {
      setFullConnect(false);
      return;
    }
    if (!fullConnect || !readConnected || readFlow.pending || writeFlow.pending) return;
    setFullConnect(false);
    void writeFlow.start();
  }, [fullConnect, readConnected, readFlow.pending, readFlow.error, readFlow.outcome, writeFlow]);

  async function runCommand(kind: CommandKind): Promise<void> {
    if (!connection) return;
    setConfirmDisconnect(false);
    setCommandError(null);
    setCommandNotice(null);
    const id = `gmail-${crypto.randomUUID()}`;
    try {
      const receipt = await apiClient.submitGmailConnectionCommand(connection.connection_ref, id, kind);
      if (receipt.status !== "recorded") {
        setCommandError("Probation did not record the access change. Nothing else changed.");
        return;
      }
      setCommand({ id: receipt.request_id, kind });
    } catch (cause) {
      setCommandError(cause instanceof Error ? cause.message : "Could not update Gmail access.");
    }
  }

  const setupFailure = (flow: ReturnType<typeof useGmailSetupFlow>, kind: SetupKind) => {
    if (flow.error) return flow.error;
    if (flow.initial.error instanceof Error) return flow.initial.error.message;
    if (flow.outcome === "failed" || flow.outcome === "unknown") {
      if (kind === "write" && flow.last?.reason === "readonly_setup_not_completed") {
        return "Google did not grant both change and send access, so action access is still not granted. Read access is unchanged.";
      }
      const reason = flow.last?.reason ? SETUP_REASON_COPY[flow.last.reason] : null;
      return reason ?? "Google connection did not complete.";
    }
    return null;
  };
  const readFailure = setupFailure(readFlow, "read");
  const writeFailure = setupFailure(writeFlow, "write");

  return <section aria-labelledby="connect-apps-title" className="space-y-6">
    <header className="max-w-xl space-y-2">
      <h2 id="connect-apps-title" className="section-heading">Connect apps</h2>
      <p className="section-caption">Bring your work into Probation. You choose what it can see, and every kind of task earns its own permission.</p>
    </header>
    {!isPrivate && <p className="border-t border-line pt-5 text-sm leading-6 text-ink-secondary">You're exploring a synthetic workspace. Real accounts are connected only in the private app.</p>}
    <div className="divide-y divide-line">
      {APPS.map((app) => <article key={app.id} className="grid gap-x-8 gap-y-5 py-6 first:pt-0 md:grid-cols-[minmax(200px,0.9fr)_minmax(0,1.5fr)]">
        <div className="flex items-start gap-4">
          <img src={`/integrations/${app.id}.webp`} alt="" width="44" height="44" className="shrink-0 object-contain" />
          <div className="min-w-0 space-y-1">
            <h3 className="font-medium">{app.name}</h3>
            <p className="text-sm leading-6 text-ink-secondary">{app.description}</p>
            {app.available && (isPrivate
              ? <p className="text-xs text-ink-tertiary">{accessLoading ? "Checking access…" : readConnected ? `Connection ${CONNECTION_STATE_COPY[connectionState ?? ""] ?? "Connected"}` : "No account connected"}</p>
              : <p className="text-xs text-ink-tertiary">Selected test label  ·  Not connected</p>)}
          </div>
        </div>
        <div className="min-w-0">
          {!app.available ? <p className="text-sm text-ink-tertiary md:text-right">Planned</p>
            : !isPrivate ? <div className="flex items-center gap-3"><Button disabled>Connect Gmail</Button><p className="text-xs text-ink-tertiary">Real accounts are connected only in the private app.</p></div>
            : !readConnected ? <div className="space-y-3">
              <div className="flex flex-wrap items-center gap-2">
                <Button variant="primary" onClick={() => { setAccessClosed(false); setFullConnect(false); void readFlow.start(); }} disabled={readFlow.pending || readFlow.initial.isLoading}>
                  {readFlow.pending ? "Waiting for Google..." : "Connect Gmail"}
                </Button>
                <Button onClick={() => { setAccessClosed(false); setFullConnect(true); void readFlow.start(); }} disabled={readFlow.pending || writeFlow.pending || fullConnect || readFlow.initial.isLoading}>
                  {fullConnect ? "Step 1 of 2: read access" : "Connect with action access"}
                </Button>
              </div>
              <p className="max-w-md text-xs leading-5 text-ink-tertiary">Read-only asks for mailbox reading only. Action access opens a second Google consent showing read, change and send; change and send are required for actions, and you still approve every action. You can choose either option now or add action access later.</p>
            </div>
            : <div className="space-y-4">
              <div className="grid gap-5 sm:grid-cols-2">
                <div className="space-y-1">
                  <p className="text-xs uppercase tracking-wide text-ink-tertiary">Read access</p>
                  <p role="status" className="text-sm font-medium text-brand">{accessLoading ? "Checking access…" : "Connected  /  read-only"}</p>
                  <p className="text-xs leading-5 text-ink-secondary">Only the selected test label. The rest of the mailbox is never read.</p>
                </div>
                <div className="space-y-1">
                  <p className="text-xs uppercase tracking-wide text-ink-tertiary">Action access</p>
                  <p className="text-sm font-medium">{writeFlow.initial.isLoading ? "Checking…" : writeConnected ? "Granted" : "Not granted"}</p>
                  <p className="text-xs leading-5 text-ink-secondary">Archive, label, send or forward - only after you review each decision.</p>
                </div>
              </div>
              <div className="flex flex-wrap items-center gap-2 border-t border-line pt-4">
                {!writeConnected && connectionState !== "DISCONNECTED" && <Button onClick={() => void writeFlow.start()} disabled={writeFlow.pending || writeFlow.initial.isLoading || command !== null}>
                  {writeFlow.pending ? "Waiting for Google..." : "Grant read, change and send"}
                </Button>}
                {connectionState === "ACTIVE" && <Button onClick={() => void runCommand("pause")} disabled={command !== null}>Pause access</Button>}
                {connectionState === "PAUSED" && <Button variant="primary" onClick={() => void runCommand("resume")} disabled={command !== null}>Resume access</Button>}
                {connectionState !== "DISCONNECTED" && (confirmDisconnect
                  ? <span className="flex flex-wrap items-center gap-2">
                    <span className="text-sm text-ink-secondary">Disconnect Gmail?</span>
                    <Button variant="danger" onClick={() => void runCommand("disconnect")} disabled={command !== null}>Yes, disconnect</Button>
                    <Button variant="ghost" onClick={() => setConfirmDisconnect(false)}>Keep connected</Button>
                  </span>
                  : <Button variant="danger" onClick={() => setConfirmDisconnect(true)} disabled={command !== null}>Disconnect Gmail</Button>)}
                {command !== null && <span role="status" className="text-sm text-ink-secondary">Applying access change...</span>}
              </div>
            </div>}
        </div>
      </article>)}
    </div>
    <div aria-live="polite" className="space-y-3 text-sm leading-6">
      {readFlow.pending && <p role="status">{fullConnect ? "Step 1 of 2. " : ""}Finish sign-in in the Google window and approve read access to the configured test account. {fullConnect ? "A second Google window will then ask for action access. Keep this page open." : "You can keep this page open."}</p>}
      {writeFlow.pending && <p role="status">Step 2 of 2. Finish sign-in in the Google window and approve action access for the same test account. You can keep this page open.</p>}
      {readFlow.outcome === "succeeded" && readConnected && !readFlow.pending && <p>Google read access is registered. Email processing and suggestions have their own status; connecting does not grant permission to send or change anything.</p>}
      {writeFlow.outcome === "succeeded" && writeConnected && !writeFlow.pending && <p>Action access is granted. Probation may archive, label, send or forward only after you review that decision, and only for this account.</p>}
      {commandNotice && <p>{commandNotice}</p>}
      {readFailure && <p role="alert" className="text-status-danger">{readFailure} <a href="#/more/help" className="inline-flex min-h-11 items-center underline underline-offset-4">Setup help</a></p>}
      {writeFailure && <p role="alert" className="text-status-danger">{writeFailure} <a href="#/more/help" className="inline-flex min-h-11 items-center underline underline-offset-4">Setup help</a></p>}
      {commandError && <p role="alert" className="text-status-danger">{commandError}</p>}
    </div>
    <p className="max-w-xl text-xs leading-5 text-ink-secondary">Google access and earned permission are different. You do not need an earned permission to grant action access or approve one action yourself. Automatic actions need their own evidence and checks. Your owner session signs you into Probation; Google consent is separate. Disconnecting ends both grants and requires consent again. Calendar and Drive are planned integrations. App names and icons belong to their respective owners.</p>
  </section>;
}
