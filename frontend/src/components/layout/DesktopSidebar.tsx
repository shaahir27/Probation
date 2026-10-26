import { Home, Inbox, ArrowUpRight, Shield, MoreHorizontal, Eye, Link2 } from "lucide-react";
import { ProbationMark } from "./ProbationMark";

interface DesktopSidebarProps { currentTab: string; currentSection?: string; queueCount: number }
export function DesktopSidebar({ currentTab, currentSection, queueCount }: DesktopSidebarProps) {
  const destinations = [
    { id: "home", label: "Overview", icon: Home },
    { id: "queue", label: "Review", icon: Inbox },
    { id: "actions", label: "Activity", icon: ArrowUpRight },
    { id: "permissions", label: "Permissions", icon: Shield },
  ];
  return <aside className="workspace-sidebar hidden md:flex">
    <a href="#/home" className="workspace-brand" aria-label="Probation overview">
      <ProbationMark className="h-10 w-9 text-brand" />
      <span><span className="block font-serif text-[26px] leading-none tracking-[-0.02em]">Probation</span><span className="mt-2 flex items-center gap-1.5 text-xs text-ink-tertiary"><span aria-hidden="true" className="h-1.5 w-1.5 rounded-full bg-accent ring-1 ring-ink" />Permission, earned.</span></span>
    </a>
    <p className="px-3 text-xs text-ink-tertiary mb-3">Your email workspace</p>
    <nav aria-label="Main navigation" className="space-y-1">
      {destinations.map(({ id, label, icon: Icon }) => <a key={id} href={`#/${id}`} aria-current={currentTab === id ? "page" : undefined}
        aria-label={id === "queue" ? `Review emails${queueCount > 0 ? `, ${queueCount} waiting` : ""}` : undefined}
        className={`workspace-nav-link ${currentTab === id ? "is-current" : ""}`}>
        <Icon aria-hidden="true" size={17} strokeWidth={1.6} /><span>{label}</span>
        {id === "queue" && queueCount > 0 && <span className="ml-auto text-xs tabular-nums text-ink">{queueCount}</span>}
      </a>)}
    </nav>
    <div className="mt-auto space-y-5 pt-8">
      <div className="sidebar-principle"><Eye aria-hidden="true" size={16} /><p>It starts by watching.<br /><span className="text-ink-tertiary">You stay in control.</span></p></div>
      <div className="space-y-1">
        <a href="#/more/connections" aria-current={currentTab === "more" && currentSection === "connections" ? "page" : undefined} className={`workspace-nav-link ${currentTab === "more" && currentSection === "connections" ? "is-current" : ""}`}><Link2 aria-hidden="true" size={17} strokeWidth={1.6} /><span>Connect apps</span></a>
        <a href="#/more/insights" aria-current={currentTab === "more" && currentSection !== "connections" ? "page" : undefined} className={`workspace-nav-link ${currentTab === "more" && currentSection !== "connections" ? "is-current" : ""}`}><MoreHorizontal aria-hidden="true" size={17} strokeWidth={1.6} /><span>More</span></a>
      </div>
    </div>
  </aside>;
}
