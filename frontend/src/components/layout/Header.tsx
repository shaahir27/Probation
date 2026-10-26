import { Clock } from "lucide-react";

interface HeaderProps {
  title: string;
  mode?: string;
  simulatedDate?: string;
  profile?: "private" | "synthetic" | null;
  onSignOut?: () => void;
}

export function Header({ title, mode = "live", simulatedDate, profile, onSignOut }: HeaderProps) {
  return <header className="min-h-12 border-b border-line bg-canvas sticky top-0 z-30 px-4 sm:px-6 flex items-center justify-between gap-3">
    <p className="font-serif text-lg text-ink font-normal tracking-tight">Probation <span className="font-sans text-sm text-ink-secondary">/ {title}</span></p>
    <div className="flex items-center gap-3">
      {simulatedDate && mode === "replay" ? <div className="flex items-center gap-2 text-xs text-ink-secondary">
        <Clock aria-hidden="true" className="w-3.5 h-3.5 text-brand" />
        <span>Demo date: <strong className="text-ink font-mono">{simulatedDate.split("T")[0]}</strong></span>
      </div> : <span className="hidden sm:inline text-xs text-ink-secondary">{profile === "synthetic" ? "Demo data" : "Private account"}</span>}
      {onSignOut && <button type="button" onClick={onSignOut} className="min-h-11 px-2 text-xs text-ink-secondary underline underline-offset-4">Sign out</button>}
    </div>
  </header>;
}
