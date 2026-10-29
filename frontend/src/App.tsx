import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  useActionsRead,
  usePermissionsRead,
  useQueueRead,
  useReplayStateRead,
  useWatchingRead,
  panelStatus,
  queryKeys,
} from "./api/queries";
import { useAdminCommandFlow, useReviewFlow, useUndoFlow } from "./api/mutations";
import { apiClient } from "./api/client";
import type { QueueItem } from "./api/types";
import { OwnerSessionProvider, useOwnerSession } from "./auth/OwnerSession";
import { DesktopSidebar } from "./components/layout/DesktopSidebar";
import { MobileNav } from "./components/layout/MobileNav";
import { Header } from "./components/layout/Header";
import { StatePanel } from "./components/common/StatePanel";
import { CommandStatus } from "./components/common/CommandStatus";
import { HomeView } from "./views/HomeView";
import { ReviewWorkspace } from "./views/ReviewWorkspace";
import { ActionsView } from "./views/ActionsView";
import { PermissionsView } from "./views/PermissionsView";
import { MoreView } from "./views/MoreView";
import { SignInView } from "./views/SignInView";
import { ItemDetailView } from "./views/ItemDetailView";
import { WatchingView } from "./views/WatchingView";
import { RequestStatusView } from "./views/RequestStatusView";
import { moreTitle, navigate, parseRoute, primaryPage, queueGate, setQueryFilter, Route, QueueGate } from "./navigation";

const TITLES: Record<string, string> = {
  home: "Overview",
  queue: "Review",
  item: "Review",
  watching: "Watching",
  "watching-item": "Watching",
  actions: "Activity",
  permissions: "Permissions",
  more: "More",
  request: "Request status",
  "not-found": "Page not found",
};

function DemoResetButton() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const reset = async () => {
    setBusy(true);
    setError(null);
    try {
      await apiClient.resetDemo();
      window.location.reload();
    } catch {
      setError("The demo could not be reset. Try again.");
      setBusy(false);
    }
  };
  return (
    <span className="inline-flex flex-wrap items-center gap-2">
      <button
        type="button"
        onClick={() => void reset()}
        disabled={busy}
        className="min-h-11 rounded-lg border border-line bg-surface px-3 text-xs font-semibold text-ink disabled:opacity-50"
      >
        {busy ? "Resetting…" : "Reset demo"}
      </button>
      {error !== null && <span role="alert" className="text-status-danger">{error}</span>}
    </span>
  );
}

export default function App() {
  return (
    <OwnerSessionProvider>
      <Workspace />
    </OwnerSessionProvider>
  );
}

function Workspace() {
  const session = useOwnerSession();
  const client = useQueryClient();
  const authenticated = session.status === "signed-in";
  const [route, setRoute] = useState<Route>(() => parseRoute(window.location.hash));
  // Declared with the other hooks: the auth gate below returns early, and a hook after it would
  // change the hook count between renders.
  const seenRows = useRef(new Map<string, QueueItem>());
  const [adminCommands, setAdminCommands] = useState<string[]>([]);
  const admin = useAdminCommandFlow();

  const queue = useQueueRead(authenticated);
  const watching = useWatchingRead(authenticated);
  const actions = useActionsRead(authenticated);
  const permissions = usePermissionsRead(authenticated);
  const replay = useReplayStateRead(authenticated);
  const reads = useMemo(
    () => [queue, watching, actions, permissions, replay],
    [queue, watching, actions, permissions, replay],
  );
  const status = panelStatus(reads);
  const coreStatus = panelStatus([queue, watching, actions, permissions]);

  // Route changes drive the view; the browser keeps the history entries.
  useEffect(() => {
    const onHashChange = () => setRoute(parseRoute(window.location.hash));
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  // A 401/403 fails closed: the session ends, cached private rows are dropped and no
  // placeholder data is shown.
  const lastLockedGeneration = useRef(-1);
  useEffect(() => {
    if (status.isLocked && lastLockedGeneration.current !== session.generation) {
      lastLockedGeneration.current = session.generation;
      session.lock(
        status.errorMessage ?? "Probation cannot show this account's data with the current sign-in.",
      );
    }
  }, [session, status.isLocked, status.errorMessage]);

  useEffect(() => {
    // Any response from a previous generation is already rejected by the client; this
    // keeps the UI honest about which session the numbers belong to.
    if (!authenticated) setAdminCommands([]);
  }, [authenticated, session.generation]);

  const onRecorded = useCallback((requestId: string) => {
    navigate({ page: "request", id: requestId });
  }, []);

  const review = useReviewFlow(onRecorded);
  const undo = useUndoFlow(onRecorded);

  const onCommandSettled = useCallback(() => {
    client.invalidateQueries({ queryKey: queryKeys.habits });
    client.invalidateQueries({ queryKey: queryKeys.exams });
    client.invalidateQueries({ queryKey: queryKeys.queue });
  }, [client]);

  useEffect(() => {
    const ids = admin.submitted.map((entry) => entry.commandId);
    if (ids.length > 0) setAdminCommands((current) => Array.from(new Set([...current, ...ids])));
  }, [admin.submitted]);

  if (session.profile === null) {
    return (
      <main className="min-h-screen bg-canvas p-6 text-ink">
        {session.bootstrapError !== null ? (
          <StatePanel
            state="error"
            title="Probation is not reachable"
            description={session.bootstrapError}
            onRetry={() => void session.loadBootstrap()}
            retryLabel="Try again"
          />
        ) : (
          <p role="status" className="text-sm">Connecting to Probation…</p>
        )}
      </main>
    );
  }

  if ((session.profile === "private" || session.demoLogin) && session.status === "unknown") {
    return (
      <main className="min-h-screen bg-canvas p-6 text-ink">
        <p role="status" className="text-sm">Restoring your session…</p>
      </main>
    );
  }

  if ((session.profile === "private" || session.demoLogin) && !authenticated) {
    const finishSignIn = async (attempt: Promise<boolean>) => {
      const ok = await attempt;
      if (!ok) return;
      // Only a bare URL normalises to Home: a deep-linked route must survive sign-in,
      // not be overwritten by it.
      const hash = window.location.hash;
      if (hash === "" || hash === "#" || hash === "#/") navigate({ page: "home" });
    };
    return (
      <SignInView
        onSubmit={(token) => finishSignIn(session.signIn(token))}
        onSignIn={(email, password) => finishSignIn(session.signInAccount(email, password))}
        onRegister={(email, password) => finishSignIn(session.registerAccount(email, password))}
        onDemo={session.demoLogin ? session.enterDemo : undefined}
        error={session.errorMessage}
        busy={session.status === "checking"}
      />
    );
  }

  const tab = primaryPage(route);
  const items = queue.data?.items ?? [];
  const queueTotal = queue.data?.total_count ?? items.length;
  for (const row of items) seenRows.current.set(row.id, row);
  const openRow = (id: string): QueueItem | undefined =>
    items.find((row) => row.id === id) ?? seenRows.current.get(id);
  const watchingItems = watching.data?.items ?? [];
  const gate = queueGate(route);
  const setGate = (next: QueueGate) => navigate(setQueryFilter({ page: "queue" }, "gate", next === "all" ? null : next));

  return (
    <div className="flex min-h-screen flex-col border-t-4 border-accent bg-canvas font-sans text-ink selection:bg-brand selection:text-brand-on md:flex-row">
      <DesktopSidebar currentTab={tab} currentSection={route.page === "more" ? route.section ?? "connections" : undefined} queueCount={queueTotal} />

      <div className="flex min-h-screen min-w-0 flex-1 flex-col pb-24 md:pb-6">
        <Header
          title={route.page === "more" ? moreTitle(route.section) : TITLES[route.page] ?? "Probation"}
          mode={replay.data?.mode ?? "live"}
          simulatedDate={replay.data?.simulated_date ?? undefined}
          profile={session.profile}
          onSignOut={session.profile === "private" || session.authRequired ? () => session.signOut() : undefined}
        />

        <main className="mx-auto w-full max-w-[1280px] flex-1 px-5 py-7 sm:px-6 lg:px-8">
          {session.profile === "synthetic" && (
            <div className="mb-4 flex flex-wrap items-center justify-between gap-2 rounded-xl border border-line bg-surface px-4 py-2 text-xs leading-5 text-ink-secondary">
              <p>Synthetic workspace. It resets every 6 hours from a generated snapshot; the private product keeps your own history and never uses these rows.</p>
              <DemoResetButton />
            </div>
          )}
          <div role="status" aria-live="polite">
            <p className="sr-only">
              {coreStatus.isStale
                ? "The data on this page is out of date."
                : coreStatus.updatedAt !== null
                  ? `Data refreshed at ${new Date(coreStatus.updatedAt).toISOString()}.`
                  : ""}
            </p>
          </div>

          {coreStatus.isStale && !coreStatus.isLoading && (
            <StatePanel
              state="stale"
              title="This data is out of date"
              description={`Probation last read this successfully at ${
                coreStatus.updatedAt === null ? "an unknown time" : new Date(coreStatus.updatedAt).toLocaleString()
              }. The list may no longer match what is recorded. Nothing on this page has changed because of it.`}
              onRetry={() => {
                void queue.refetch();
                void watching.refetch();
                void actions.refetch();
                void permissions.refetch();
              }}
              retryLabel="Refresh now"
              retrying={coreStatus.isFetching}
            />
          )}

          {coreStatus.errorMessage !== null && !coreStatus.isStale && !coreStatus.isLocked && (
            <StatePanel
              state="error"
              title="Probation could not read this"
              description={coreStatus.errorMessage}
              onRetry={() => {
                void queue.refetch();
                void watching.refetch();
                void actions.refetch();
                void permissions.refetch();
                void replay.refetch();
              }}
              retrying={coreStatus.isFetching}
            />
          )}

          <CommandStatus commandIds={adminCommands} onSettled={onCommandSettled} />

          {coreStatus.isLoading && (
            <div className="space-y-4" aria-hidden="true">
              <div className="h-28 rounded-2xl border border-line bg-surface" />
              <div className="h-64 rounded-2xl border border-line bg-surface" />
            </div>
          )}

          {!coreStatus.isLoading && (
            <>
              {route.page === "home" && (
                <HomeView
                  queueItems={items}
                  queueTotal={queueTotal}
                  handledCount={queue.data?.handled_count ?? 0}
                  expiredCount={queue.data?.expired_count ?? 0}
                  licences={permissions.data?.licences ?? []}
                  actions={actions.data?.actions ?? []}
                  profile={session.profile ?? "synthetic"}
                />
              )}

              {(route.page === "queue" || route.page === "item") && (
                <ReviewWorkspace
                  items={items}
                  digests={queue.data?.digests ?? []}
                  handledCount={queue.data?.handled_count ?? 0}
                  handledDigests={queue.data?.handled_digests ?? []}
                  expiredCount={queue.data?.expired_count ?? 0}
                  expiredDigests={queue.data?.expired_digests ?? []}
                  gate={gate}
                  onGateChange={setGate}
                  selectedId={route.page === "item" ? route.id : null}
                  // The authoritative content comes from the by-id detail read. The queue row is
                  // only the preview, and a background list refresh must never remove it: when
                  // another tab answers an item it leaves the queue, which would unmount the
                  // screen (and the conflict message) the owner is still reading.
                  selectedItem={route.page === "item" ? openRow(route.id) : undefined}
                  authenticated={authenticated}
                  review={review}
                  onSelect={(item) => navigate({ page: "item", id: item.id })}
                  onBack={() => navigate({ page: "queue" })}
                />
              )}

              {route.page === "watching" && (
                <WatchingView
                  items={watchingItems}
                  errorMessage={watching.error instanceof Error ? watching.error.message : null}
                  onRetry={() => void watching.refetch()}
                />
              )}

              {route.page === "watching-item" && (
                <ItemDetailView
                  id={route.id}
                  item={watchingItems.find((item) => item.id === route.id)}
                  authenticated={authenticated}
                  readOnly
                  review={{ busy: false, conflict: null, error: null, submit: async () => null, refresh: () => undefined }}
                  onBack={() => navigate({ page: "watching" })}
                />
              )}

              {route.page === "actions" && (
                <ActionsView
                  actions={actions.data?.actions ?? []}
                  busyId={undo.busyId}
                  conflict={undo.conflict}
                  error={undo.error}
                  onUndo={(actionId) => {
                    void undo.undo(actionId);
                  }}
                />
              )}

              {route.page === "permissions" && (
                <PermissionsView
                  licences={permissions.data?.licences ?? []}
                  errorMessage={permissions.error instanceof Error ? permissions.error.message : null}
                  onRetry={() => void permissions.refetch()}
                />
              )}

              {route.page === "more" && (
                <MoreView
                  section={route.section ?? ""}
                  profile={session.profile}
                  authenticated={authenticated}
                />
              )}

              {route.page === "request" && <RequestStatusView id={route.id} authenticated={authenticated} />}

              {route.page === "not-found" && (
                <StatePanel
                  state="unsupported"
                  title="Page not found"
                  description="This address is not part of Probation. Nothing was changed and nothing was sent."
                  action={
                    <a href="#/home" className="min-h-11 inline-flex items-center underline underline-offset-4 text-sm">
                      Go to Home
                    </a>
                  }
                />
              )}
            </>
          )}
        </main>
      </div>

      <MobileNav currentTab={tab} queueCount={queueTotal} />
    </div>
  );
}
