import { FormEvent, useState } from "react";
import { Button } from "../components/common/Button";

interface SignInViewProps {
  onSubmit: (token: string) => Promise<void>;
  error: string | null;
  busy: boolean;
}

export function SignInView({ onSubmit, error, busy }: SignInViewProps) {
  const [token, setToken] = useState("");

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (token.trim()) await onSubmit(token.trim());
  };

  return (
    <main className="min-h-screen bg-canvas text-ink grid place-items-center px-4">
      <form onSubmit={submit} className="w-full max-w-md space-y-5">
        <div className="space-y-2">
          <p className="text-sm text-ink-secondary">Probation · Private account</p>
          <h1 className="font-serif text-2xl font-normal">Sign in to your account</h1>
          <p className="text-sm text-ink-secondary leading-relaxed">
            Enter the owner key configured for this app. It stays in memory and is cleared when you sign out.
          </p>
        </div>
        <label htmlFor="owner-key" className="block text-sm font-medium">Owner key</label>
        <input
          id="owner-key"
          type="password"
          autoComplete="current-password"
          value={token}
          onChange={(event) => setToken(event.target.value)}
          aria-describedby={error ? "sign-in-error" : "owner-key-help"}
          aria-invalid={Boolean(error)}
          className="w-full min-h-11 rounded-md border border-line bg-surface px-3 text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus"
          required
        />
        {!error && <p id="owner-key-help" className="text-xs text-ink-tertiary">The key is sent only to this app.</p>}
        {error && <p id="sign-in-error" role="alert" className="text-sm text-status-danger">{error}</p>}
        <Button type="submit" variant="primary" size="md" disabled={busy || !token.trim()}>
          {busy ? "Checking…" : "Continue"}
        </Button>
      </form>
    </main>
  );
}
