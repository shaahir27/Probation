import { FormEvent, useState } from "react";
import { ArrowRight, LockKeyhole } from "lucide-react";
import { Button } from "../components/common/Button";
import { ProbationMark } from "../components/layout/ProbationMark";

type AuthMode = "account" | "register" | "owner";

interface SignInViewProps {
  onSubmit: (token: string) => Promise<void>;
  onSignIn: (email: string, password: string) => Promise<void>;
  onRegister: (email: string, password: string) => Promise<void>;
  error: string | null;
  busy: boolean;
}

export function SignInView({ onSubmit, onSignIn, onRegister, error, busy }: SignInViewProps) {
  const [mode, setMode] = useState<AuthMode>("account");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [token, setToken] = useState("");

  const changeMode = (next: AuthMode) => {
    setMode(next);
    setPassword("");
    setToken("");
  };
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (mode === "owner") {
      if (token.trim()) await onSubmit(token.trim());
    } else if (mode === "register") {
      if (email.trim() && password.length >= 8) await onRegister(email.trim(), password);
    } else if (email.trim() && password) {
      await onSignIn(email.trim(), password);
    }
  };

  const registering = mode === "register";
  const ownerMode = mode === "owner";
  const canSubmit = ownerMode
    ? Boolean(token.trim())
    : Boolean(email.trim()) && password.length >= (registering ? 8 : 1);

  return <main className="sign-in-workspace border-t-4 border-accent" data-ui="sign-in">
    <section className="sign-in-intro" aria-label="About Probation">
      <a href="#/home" className="inline-flex items-center gap-3 text-brand-on"><ProbationMark className="h-12 w-10 text-accent" /><span className="font-serif text-3xl tracking-tight">Probation</span></a>
      <div className="space-y-5 max-w-md">
        <p className="inline-flex items-center gap-2 text-sm text-brand-muted"><span aria-hidden="true" className="h-1.5 w-1.5 rounded-full bg-accent" />Permission, earned.</p>
        <h2 className="font-serif text-[clamp(2.6rem,4.2vw,3.9rem)] font-normal leading-[1.02] tracking-[-0.03em] text-brand-on">A second opinion.<br />Your final say.</h2>
        <p className="text-sm leading-6 text-brand-muted">An email assistant that explains its suggestions, checks relevant public sources, and earns permission from your decisions.</p>
      </div>
      <div className="sign-in-method"><span>Read</span><span aria-hidden="true">→</span><span>Review</span><span aria-hidden="true">→</span><span>Decide</span></div>
    </section>
    <section className="sign-in-access">
      <form onSubmit={submit} className="w-full max-w-sm space-y-5">
        <div className="space-y-3 mb-8">
          <p className="inline-flex items-center gap-2 text-xs text-ink-secondary"><LockKeyhole aria-hidden="true" size={14} />Private account</p>
          <h1 className="page-title text-[32px]">{registering ? "Create your account" : "Sign in to your account"}</h1>
          <p className="text-sm text-ink-secondary leading-6">
            {ownerMode ? "Use the owner key configured for this local workspace." : registering ? "Create a local account for your own workspace." : "Open your local Probation workspace."}
          </p>
        </div>

        {!ownerMode && <div className="space-y-2">
          <label htmlFor="account-email" className="block text-sm font-medium">Email</label>
          <input id="account-email" type="email" autoComplete="username" value={email} onChange={(event) => setEmail(event.target.value)} aria-describedby={error ? "sign-in-error" : undefined} aria-invalid={Boolean(error)} className="w-full min-h-12 rounded-lg border border-line bg-surface px-3 text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus focus-visible:ring-offset-2 focus-visible:ring-offset-canvas" required />
        </div>}

        {!ownerMode ? <div className="space-y-2">
          <label htmlFor="account-password" className="block text-sm font-medium">Password</label>
          <input id="account-password" type="password" autoComplete={registering ? "new-password" : "current-password"} minLength={registering ? 8 : 1} value={password} onChange={(event) => setPassword(event.target.value)} aria-describedby={error ? "sign-in-error" : registering ? "password-help" : undefined} aria-invalid={Boolean(error)} className="w-full min-h-12 rounded-lg border border-line bg-surface px-3 text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus focus-visible:ring-offset-2 focus-visible:ring-offset-canvas" required />
          {registering && !error && <p id="password-help" className="text-xs leading-5 text-ink-tertiary">Use at least 8 characters. Your password is stored only as a local scrypt hash.</p>}
        </div> : <div className="space-y-2">
          <label htmlFor="owner-key" className="block text-sm font-medium">Owner key</label>
          <input id="owner-key" type="password" autoComplete="current-password" value={token} onChange={(event) => setToken(event.target.value)} aria-describedby={error ? "sign-in-error" : "owner-key-help"} aria-invalid={Boolean(error)} className="w-full min-h-12 rounded-lg border border-line bg-surface px-3 text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus focus-visible:ring-offset-2 focus-visible:ring-offset-canvas" required />
          {!error && <p id="owner-key-help" className="text-xs leading-5 text-ink-tertiary">Your key is exchanged for a short-lived session and is never saved in browser storage.</p>}
        </div>}

        {error && <p id="sign-in-error" role="alert" className="text-sm text-status-danger">{error}</p>}
        <Button type="submit" variant="primary" size="lg" className="w-full justify-between" disabled={busy || !canSubmit}>
          {busy ? "Checking…" : registering ? "Create account" : ownerMode ? "Continue" : "Sign in"}<ArrowRight size={16} aria-hidden="true" />
        </Button>

        <div className="space-y-2 border-t border-line pt-4 text-sm">
          {mode === "account" ? <>
            <button type="button" className="min-h-11 w-full text-left font-medium text-brand underline-offset-4 hover:underline" onClick={() => changeMode("register")}>Create an account</button>
            <button type="button" className="min-h-11 w-full text-left text-ink-secondary underline-offset-4 hover:underline" onClick={() => changeMode("owner")}>Use owner key instead</button>
          </> : <button type="button" className="min-h-11 w-full text-left font-medium text-brand underline-offset-4 hover:underline" onClick={() => changeMode("account")}>Back to account sign-in</button>}
        </div>
        <p className="text-xs leading-5 text-ink-tertiary">Local session. Refreshing keeps you signed in for up to 30 minutes of inactivity; sign out ends the session.</p>
      </form>
    </section>
  </main>;
}
