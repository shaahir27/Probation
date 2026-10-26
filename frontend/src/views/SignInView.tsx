import { FormEvent, useState } from "react";
import { ArrowRight, LockKeyhole } from "lucide-react";
import { Button } from "../components/common/Button";
import { ProbationMark } from "../components/layout/ProbationMark";
interface SignInViewProps { onSubmit: (token: string) => Promise<void>; error: string | null; busy: boolean }
export function SignInView({ onSubmit, error, busy }: SignInViewProps) {
  const [token, setToken] = useState("");
  const submit = async (event: FormEvent<HTMLFormElement>) => { event.preventDefault(); if (token.trim()) await onSubmit(token.trim()); };
  return <main className="sign-in-workspace" data-ui="sign-in">
    <section className="sign-in-intro" aria-label="About Probation">
      <a href="#/home" className="inline-flex items-center gap-3 text-ink"><ProbationMark className="h-12 w-10 text-brand" /><span className="font-serif text-3xl tracking-tight">Probation</span></a>
      <div className="space-y-5 max-w-sm">
        <p className="text-sm text-brand">Permission, earned.</p>
        <h2 className="font-serif text-[32px] leading-tight tracking-tight">A second opinion.<br />Your final say.</h2>
        <p className="text-sm leading-6 text-ink-secondary">An email assistant that explains its suggestions, checks relevant public sources, and earns permission from your decisions.</p>
      </div>
      <div className="sign-in-method"><span>Read</span><span aria-hidden="true">→</span><span>Review</span><span aria-hidden="true">→</span><span>Decide</span></div>
    </section>
    <section className="sign-in-access">
      <form onSubmit={submit} className="w-full max-w-sm space-y-5">
        <div className="space-y-3 mb-8"><p className="inline-flex items-center gap-2 text-xs text-ink-secondary"><LockKeyhole aria-hidden="true" size={14} />Private account</p><h1 className="font-serif text-2xl font-normal">Sign in to your account</h1><p className="text-sm text-ink-secondary leading-6">Enter your owner key to open this workspace.</p></div>
        <div className="space-y-2"><label htmlFor="owner-key" className="block text-sm font-medium">Owner key</label>
          <input id="owner-key" type="password" autoComplete="current-password" value={token} onChange={(event) => setToken(event.target.value)} aria-describedby={error ? "sign-in-error" : "owner-key-help"} aria-invalid={Boolean(error)} className="w-full min-h-12 rounded-lg border border-line bg-surface px-3 text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus" required />
        </div>
        {error ? <p id="sign-in-error" role="alert" className="text-sm text-status-danger">{error}</p> : <p id="owner-key-help" className="text-xs leading-5 text-ink-tertiary">Your key is exchanged for a short-lived session on this device and is never saved in browser storage. Refreshing the page keeps you signed in; sign out ends the session.</p>}
        <Button type="submit" variant="primary" size="lg" className="w-full justify-between" disabled={busy || !token.trim()}>{busy ? "Checking…" : "Continue"}<ArrowRight size={16} aria-hidden="true" /></Button>
      </form>
    </section>
  </main>;
}
