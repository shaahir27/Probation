import { useEffect, useState } from "react";
import { Radio, ExternalLink, ShieldAlert, RefreshCw } from "lucide-react";
import { apiClient } from "../api/client";
import { BoardResponse, BoardEntry } from "../api/types";
import { Badge } from "../components/common/Badge";
import { Button } from "../components/common/Button";
import { ErrorBanner } from "../components/common/ErrorBanner";

export const RadarView: React.FC = () => {
  const [board, setBoard] = useState<BoardResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchRadar = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await apiClient.getBoard("radar");
      setBoard(data);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load Radar board");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchRadar();
  }, []);

  if (loading) {
    return (
      <div className="space-y-4 animate-pulse">
        <div className="h-28 bg-surface rounded-xl border border-border" />
        <div className="h-48 bg-surface rounded-xl border border-border" />
      </div>
    );
  }

  if (error) {
    return <ErrorBanner message={error} onRetry={fetchRadar} />;
  }

  if (!board || !board.active) {
    return (
      <div className="space-y-6">
        <div className="rounded-xl bg-surface border border-border p-6 text-center space-y-3">
          <div className="w-12 h-12 rounded-full bg-surface-subtle border border-border flex items-center justify-center mx-auto text-text-muted">
            <Radio className="w-6 h-6" />
          </div>
          <h2 className="text-base font-semibold text-text-primary">Radar Board Inactive</h2>
          <p className="text-sm text-text-muted max-w-md mx-auto leading-relaxed">
            The Radar pack is not currently active on this system. In accordance with the contract,
            this board is kept strictly dormant until active data and pack permissions are enabled.
          </p>
          <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-surface-subtle border border-border text-xs text-text-muted">
            <ShieldAlert className="w-3.5 h-3.5 text-brand" />
            <span>Fail-Closed Dormancy</span>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header card */}
      <div className="rounded-xl bg-surface border border-border p-5 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-lg bg-surface-subtle border border-border flex items-center justify-center text-brand">
            <Radio className="w-5 h-5" />
          </div>
          <div>
            <h1 className="text-base font-semibold text-text-primary">Radar Board</h1>
            <p className="text-xs text-text-muted">
              Autonomous opportunity and event tracker for verified public entities
            </p>
          </div>
        </div>
        <Button variant="ghost" size="sm" onClick={fetchRadar}>
          <RefreshCw className="w-4 h-4 mr-1.5" />
          Refresh
        </Button>
      </div>

      {board.entries.length === 0 ? (
        <div className="rounded-xl bg-surface border border-border p-8 text-center text-text-muted text-sm">
          No active radar entries found.
        </div>
      ) : (
        <div className="space-y-3">
          {board.entries.map((entry: BoardEntry) => (
            <div
              key={entry.id}
              className="rounded-xl bg-surface border border-border p-4 hover:border-brand/40 transition-colors space-y-2"
            >
              <div className="flex items-start justify-between gap-3">
                <div className="space-y-1">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium text-text-primary">{entry.entity}</span>
                    <Badge variant="brand">{entry.status}</Badge>
                  </div>
                  <p className="text-xs text-text-muted">
                    Updated {new Date(entry.updated_at).toLocaleString()}
                  </p>
                </div>
              </div>

              {entry.sources && entry.sources.length > 0 && (
                <div className="pt-2 border-t border-border flex flex-wrap gap-2 text-xs">
                  <span className="text-text-muted">Sources:</span>
                  {entry.sources.map((src, i) => (
                    <a
                      key={i}
                      href={src.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-1 text-brand hover:underline"
                    >
                      {src.title || src.url}
                      <ExternalLink className="w-3 h-3" />
                    </a>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
