import {
  ShieldCheck,
  Award,
  Compass,
  Lock,
  ExternalLink,
  Database,
  Sparkles,
} from "lucide-react";

export default function App() {

  return (
    <div className="min-h-screen bg-[#090d16] text-slate-100 flex flex-col font-sans selection:bg-sky-500 selection:text-white">
      {/* Top Header */}
      <header className="border-b border-slate-800 bg-slate-900/60 backdrop-blur-md sticky top-0 z-50">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
          <div className="flex items-center space-x-3">
            <div className="w-9 h-9 rounded-xl bg-gradient-to-tr from-sky-500 to-indigo-600 flex items-center justify-center shadow-lg shadow-sky-500/20">
              <ShieldCheck className="w-5 h-5 text-white" />
            </div>
            <div>
              <span className="font-bold text-lg tracking-tight bg-gradient-to-r from-white via-slate-200 to-slate-400 bg-clip-text text-transparent">
                Probation
              </span>
              <span className="ml-2 px-2 py-0.5 text-xs font-medium rounded-full bg-sky-950 text-sky-400 border border-sky-800/60">
                Phase 0 Scaffold
              </span>
            </div>
          </div>

          <div className="flex items-center space-x-4">
            <div className="flex items-center space-x-2 text-xs text-slate-400 bg-slate-800/70 px-3 py-1.5 rounded-lg border border-slate-700/60">
              <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span>
              <span>Clock: <strong className="text-slate-200">Replay Monotonic</strong></span>
            </div>
            <div className="flex items-center space-x-2 text-xs text-slate-400 bg-slate-800/70 px-3 py-1.5 rounded-lg border border-slate-700/60">
              <Lock className="w-3.5 h-3.5 text-amber-400" />
              <span>Budget Cap: <strong className="text-slate-200">$20.00 USD</strong></span>
            </div>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 flex-1 w-full">
        {/* Hero Section */}
        <div className="mb-8 p-6 rounded-2xl glass-panel relative overflow-hidden">
          <div className="absolute -right-12 -top-12 w-64 h-64 bg-sky-500/10 rounded-full blur-3xl pointer-events-none"></div>
          <div className="relative z-10 flex flex-col md:flex-row md:items-center justify-between gap-6">
            <div>
              <div className="flex items-center space-x-2 text-xs font-semibold uppercase tracking-wider text-sky-400 mb-2">
                <Sparkles className="w-4 h-4" />
                <span>Earned Autonomy Engine</span>
              </div>
              <h1 className="text-2xl sm:text-3xl font-extrabold text-white tracking-tight">
                Driving Test on Your Own Past
              </h1>
              <p className="mt-2 text-sm text-slate-400 max-w-2xl leading-relaxed">
                Probation observes user footprints in mail, calendar, files, and chains under strict temporal isolation. It predicts actions offline in shadow mode and earns licences only after statistical proof ($LB_{`{0.95}`}$) and trick-question exam validation.
              </p>
            </div>
            <div className="flex items-center gap-3">
              <a
                href="docs/CONTRACT.md"
                className="px-4 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 border border-slate-700 text-xs font-medium text-slate-200 transition-colors flex items-center gap-1.5"
              >
                <span>Contract Rules</span>
                <ExternalLink className="w-3.5 h-3.5 text-slate-400" />
              </a>
            </div>
          </div>
        </div>

        {/* 4 Autonomy Levels Bar */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
          <div className="p-4 rounded-xl glass-panel border-l-4 border-l-slate-500">
            <span className="text-xs uppercase font-semibold text-slate-400">Level 0</span>
            <h3 className="font-bold text-white text-base mt-1">Watch</h3>
            <p className="text-xs text-slate-400 mt-1">Shadow evaluation only; zero autonomous side effects.</p>
          </div>

          <div className="p-4 rounded-xl glass-panel border-l-4 border-l-sky-500">
            <span className="text-xs uppercase font-semibold text-sky-400">Level 1</span>
            <h3 className="font-bold text-white text-base mt-1">Suggest</h3>
            <p className="text-xs text-slate-400 mt-1">One-click human suggestions queued for approval.</p>
          </div>

          <div className="p-4 rounded-xl glass-panel border-l-4 border-l-amber-500">
            <span className="text-xs uppercase font-semibold text-amber-400">Level 2</span>
            <h3 className="font-bold text-white text-base mt-1">Do with Undo</h3>
            <p className="text-xs text-slate-400 mt-1">Autonomous action held in a time-window with 1-click recall.</p>
          </div>

          <div className="p-4 rounded-xl glass-panel border-l-4 border-l-emerald-500">
            <span className="text-xs uppercase font-semibold text-emerald-400">Level 3</span>
            <h3 className="font-bold text-white text-base mt-1">Do Silently</h3>
            <p className="text-xs text-slate-400 mt-1">Immediate execution for high-volume, easily reversible actions.</p>
          </div>
        </div>

        {/* System Architecture Cards */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          <div className="p-5 rounded-xl glass-panel">
            <div className="w-8 h-8 rounded-lg bg-sky-500/20 text-sky-400 flex items-center justify-center mb-3">
              <Database className="w-4 h-4" />
            </div>
            <h4 className="font-semibold text-white text-sm">WAL Ledger & Storage</h4>
            <p className="text-xs text-slate-400 mt-1 leading-relaxed">
              SQLite WAL mode with SHA-256 hash-chained immutable audit ledger.
            </p>
          </div>

          <div className="p-5 rounded-xl glass-panel">
            <div className="w-8 h-8 rounded-lg bg-emerald-500/20 text-emerald-400 flex items-center justify-center mb-3">
              <Compass className="w-4 h-4" />
            </div>
            <h4 className="font-semibold text-white text-sm">Asymmetric Tavily Vetting</h4>
            <p className="text-xs text-slate-400 mt-1 leading-relaxed">
              The web can only warn or restrict autonomy; only your personal history can build trust.
            </p>
          </div>

          <div className="p-5 rounded-xl glass-panel">
            <div className="w-8 h-8 rounded-lg bg-indigo-500/20 text-indigo-400 flex items-center justify-center mb-3">
              <Award className="w-4 h-4" />
            </div>
            <h4 className="font-semibold text-white text-sm">Trick-Question Exam Board</h4>
            <p className="text-xs text-slate-400 mt-1 leading-relaxed">
              Deterministic counterfactual exams test invariance and safety before granting licences.
            </p>
          </div>
        </div>
      </main>

      {/* Footer */}
      <footer className="border-t border-slate-800/80 py-4 text-center text-xs text-slate-500">
        Probation Engine · NVIDIA Global AI Hackathon (Personal AI Track) · Nebius Token Factory · Tavily Grounding
      </footer>
    </div>
  );
}
