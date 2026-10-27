import { LogOut } from "lucide-react";
import { ProbationMark } from "./ProbationMark";
interface HeaderProps { title: string; mode?: string; simulatedDate?: string; profile?: "private" | "synthetic" | null; onSignOut?: () => void }
export function Header({ title, mode = "live", simulatedDate, profile, onSignOut }: HeaderProps) {
  return <header className="workspace-topbar">
    <div className="flex min-w-0 items-center gap-3"><ProbationMark className="h-7 w-6 text-brand md:hidden" /><span className="text-sm text-ink-secondary truncate">Workspace<span aria-hidden="true" className="mx-3 text-ink-tertiary">/</span><span className="text-ink">{title}</span></span></div>
    <div className="flex shrink-0 items-center gap-3 sm:gap-5">
      <span className="hidden items-center gap-2 text-xs text-ink-tertiary sm:inline-flex"><span aria-hidden="true" className="h-1.5 w-1.5 rounded-full bg-status-success" />{profile === "synthetic" ? "Synthetic workspace" : "Private workspace"}{mode === "replay" && simulatedDate ? ` · ${simulatedDate.split("T")[0]}` : ""}</span>
      {onSignOut && <button type="button" onClick={onSignOut} className="min-h-11 inline-flex items-center gap-2 text-xs text-ink-secondary hover:text-ink"><LogOut size={14} aria-hidden="true" /><span>Sign out</span></button>}
    </div>
  </header>;
}
