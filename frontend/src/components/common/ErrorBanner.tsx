import { AlertCircle, RefreshCw } from "lucide-react";
import { Button } from "./Button";

interface ErrorBannerProps {
  message: string;
  onRetry?: () => void;
}

export function ErrorBanner({ message, onRetry }: ErrorBannerProps) {
  return (
    <div className="p-4 rounded-xl bg-status-danger/10 border border-status-danger/30 text-ink flex items-center justify-between gap-4 my-4">
      <div className="flex items-center gap-3">
        <AlertCircle className="w-5 h-5 text-status-danger shrink-0" />
        <span className="text-sm">{message}</span>
      </div>
      {onRetry && (
        <Button size="sm" variant="secondary" onClick={onRetry} className="gap-1.5 shrink-0">
          <RefreshCw className="w-3.5 h-3.5" />
          <span>Retry</span>
        </Button>
      )}
    </div>
  );
}
