import { Clock } from "lucide-react";
import { Badge } from "../common/Badge";

interface HeaderProps {
  title: string;
  mode?: string;
  simulatedDate?: string;
}

export function Header({ title, mode = "live", simulatedDate }: HeaderProps) {
  return (
    <header className="h-16 border-b border-line nav-glass sticky top-0 z-30 px-6 flex items-center justify-between">
      <div className="flex items-center gap-3">
        <h1 className="font-serif text-xl text-ink font-normal tracking-tight capitalize">{title}</h1>
      </div>

      <div className="flex items-center gap-4">
        {/* Status chip from preview: "● AI systems online" */}
        <div className="hidden sm:flex items-center gap-2 px-3 py-1 rounded-full bg-surfaceSubtle/60 border border-line text-xs text-ink-secondary">
          <span className="w-2 h-2 rounded-full bg-status-success shadow-[0_0_8px_rgba(133,185,154,0.6)]" />
          <span>AI systems online</span>
        </div>

        {simulatedDate && mode === "replay" ? (
          <div className="flex items-center gap-2 text-xs text-ink-secondary">
            <Clock className="w-3.5 h-3.5 text-brand" />
            <span>
              Simulated: <strong className="text-ink font-mono">{simulatedDate.split("T")[0]}</strong>
            </span>
          </div>
        ) : (
          <Badge variant="subtle" className="font-medium text-[11px]">
            Live Service
          </Badge>
        )}
      </div>
    </header>
  );
}

