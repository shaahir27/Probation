import { Badge } from "../common/Badge";

interface HeaderProps {
  title: string;
  mode?: string;
  simulatedDate?: string;
}

export function Header({ title, mode = "live", simulatedDate }: HeaderProps) {
  return (
    <header className="h-16 border-b border-line nav-glass sticky top-0 z-30 px-6 flex items-center justify-between">
      <h1 className="text-lg font-bold text-ink tracking-tight capitalize">{title}</h1>

      <div className="flex items-center gap-3">
        {simulatedDate && mode === "replay" && (
          <span className="text-xs text-ink-secondary hidden sm:inline">
            Simulated: <strong className="text-ink font-mono">{simulatedDate.split("T")[0]}</strong>
          </span>
        )}

        <Badge variant={mode === "replay" ? "brand" : "success"} className="uppercase font-semibold">
          {mode === "replay" ? "Replay Mode" : "Live Service"}
        </Badge>
      </div>
    </header>
  );
}
