import { Radio, ShieldAlert } from "lucide-react";
import { BoardEntry } from "../api/types";
import { Badge } from "../components/common/Badge";
import { ExternalLink } from "../components/common/ExternalLink";
import { StatePanel, UnavailablePanel } from "../components/common/StatePanel";
import { useBoardRead } from "../api/queries";

/**
 * Radar is a read-only view of verified board rows. It is only shown when the pack is
 * actually active; otherwise it says so. There is no tracking mutation here, because the
 * board lifecycle has not been accepted, and no fixture row is ever rendered.
 */
export function RadarView({ authenticated }: { authenticated: boolean }) {
  const read = useBoardRead("radar", authenticated);
  const board = read.data ?? null;
  const errorMessage = read.error instanceof Error ? read.error.message : null;

  if (read.isLoading) {
    return <StatePanel state="loading" title="Checking the Radar board" description="Reading the board state from Probation." />;
  }
  if (errorMessage !== null) {
    return (
      <StatePanel
        state="error"
        title="Radar is unavailable"
        description={`${errorMessage} Probation will not show board rows it could not read.`}
        onRetry={() => void read.refetch()}
      />
    );
  }
  if (board === null || !board.active) {
    return (
      <UnavailablePanel
        title="Radar"
        reason="The Radar pack is not active on this system, so there is nothing to show. Opportunity tracking is not accepted for release yet; Probation will not present seeded board rows as a working feature."
        scope="Verified web facts that restrict a decision still appear on the email detail page."
      />
    );
  }
  if (board.entries.length === 0) {
    return (
      <StatePanel
        state="empty"
        title="Radar board is empty"
        description="Radar is not accepted for release yet: the pack is active but has no recorded entries, so nothing is being tracked and no board row has been seeded for this demonstration."
      />
    );
  }

  return (
    <div className="space-y-4">
      <header className="space-y-1">
        <div className="flex items-center gap-2">
          <Radio aria-hidden="true" className="h-4 w-4 text-brand" />
          <h2 className="text-base font-medium">Radar board</h2>
          <Badge variant="subtle">Read only</Badge>
        </div>
        <p className="text-sm text-ink-secondary">
          {board.entries.length} recorded {board.entries.length === 1 ? "entry" : "entries"}. Tracking and dismissal
          are not available yet: Probation cannot do this safely yet.
        </p>
      </header>
      <ul className="space-y-3">
        {board.entries.map((entry: BoardEntry) => (
          <li key={entry.id} className="space-y-2 rounded-xl border border-line bg-surface p-4">
            <div className="flex flex-wrap items-center gap-2">
              <span className="break-words text-sm font-medium">{entry.entity || "Unnamed entry"}</span>
              <Badge variant="brand">{entry.status || "Status unavailable"}</Badge>
            </div>
            <p className="text-xs text-ink-tertiary">
              {entry.updated_at ? `Updated ${entry.updated_at}` : "No update time recorded."}
            </p>
            {entry.sources.length > 0 ? (
              <div className="flex flex-wrap items-start gap-2 border-t border-line pt-2 text-xs">
                <span className="text-ink-secondary">Sources:</span>
                <ul className="flex flex-wrap gap-2">
                  {entry.sources.map((source, index) => (
                    <li key={`${source.url}-${index}`}>
                      <ExternalLink url={source.url} title={source.title} />
                    </li>
                  ))}
                </ul>
              </div>
            ) : (
              <p className="flex items-center gap-1.5 border-t border-line pt-2 text-xs text-ink-tertiary">
                <ShieldAlert aria-hidden="true" className="h-3.5 w-3.5 text-brand" />
                No source is cited for this entry.
              </p>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
