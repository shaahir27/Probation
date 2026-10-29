/**
 * Owner session: the credential boundary for the private workspace.
 *
 * The key is handed to `POST /api/session` once and immediately dropped. The server
 * returns an opaque, short-lived HttpOnly cookie, so a page refresh restores the session
 * without the key ever touching browser storage or JavaScript-readable memory. Logout
 * bumps a monotonic session generation, aborts every in-flight request, clears the cached
 * private data, and asks every registered panel to drop drafts and review bindings.
 */

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ApiError, apiClient, beginOwnerSession, clearOwnerSession, getSessionGeneration } from "../api/client";
import { clearPrivateCache } from "../api/queries";

export type SessionStatus = "unknown" | "signed-out" | "checking" | "signed-in" | "locked";
export type Profile = "private" | "synthetic";

const resetCallbacks = new Set<() => void>();

/** Panels register here to drop drafts, bindings and pending reads on session change. */
export function registerSessionReset(callback: () => void): () => void {
  resetCallbacks.add(callback);
  return () => resetCallbacks.delete(callback);
}

interface OwnerSessionValue {
  profile: Profile | null;
  authRequired: boolean;
  /** The synthetic demo asks for one click instead of opening directly. */
  demoLogin: boolean;
  status: SessionStatus;
  generation: number;
  /** Message from the last failed attempt; null once a read succeeds. */
  errorMessage: string | null;
  bootstrapError: string | null;
  loadBootstrap(): Promise<void>;
  enterDemo(): void;
  signIn(token: string): Promise<boolean>;
  signInAccount(email: string, password: string): Promise<boolean>;
  registerAccount(email: string, password: string): Promise<boolean>;
  signOut(reason?: string): void;
  /** Called by any read that returned 401/403 so the UI fails closed. */
  lock(message: string): void;
}

const OwnerSessionContext = createContext<OwnerSessionValue | null>(null);

export function OwnerSessionProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [profile, setProfile] = useState<Profile | null>(null);
  const [authRequired, setAuthRequired] = useState(false);
  const [demoLogin, setDemoLogin] = useState(false);
  const [status, setStatus] = useState<SessionStatus>("unknown");
  const [generation, setGeneration] = useState(0);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [bootstrapError, setBootstrapError] = useState<string | null>(null);

  const resetEverywhere = useCallback(() => {
    resetCallbacks.forEach((callback) => {
      try {
        callback();
      } catch {
        // A panel that cannot clean itself up still must not block the logout.
      }
    });
  }, []);

  const loadBootstrap = useCallback(async () => {
    setBootstrapError(null);
    try {
      const value = await apiClient.getBootstrap();
      setProfile(value.profile);
      setAuthRequired(value.auth_required);
      setDemoLogin(value.demo_login);
      if (!value.auth_required && !value.demo_login) {
        beginOwnerSession();
        setGeneration(getSessionGeneration());
        setStatus("signed-in");
        return;
      }
      try {
        // A refresh keeps the existing HttpOnly session; without one the owner signs in.
        const restored = await apiClient.getSession();
        if (!restored.authenticated) {
          const next = clearOwnerSession();
          setGeneration(next);
          setStatus("signed-out");
          return;
        }
        beginOwnerSession();
        setGeneration(getSessionGeneration());
        setStatus("signed-in");
      } catch (error) {
        if (error instanceof ApiError && (error.status === 401 || error.status === 403)) {
          const next = clearOwnerSession();
          setGeneration(next);
          setStatus("signed-out");
          return;
        }
        throw error;
      }
    } catch (error) {
      setBootstrapError(
        error instanceof Error ? error.message : "Probation setup could not be loaded.",
      );
    }
  }, []);

  useEffect(() => {
    void loadBootstrap();
  }, [loadBootstrap]);

  const signOut = useCallback(
    (reason?: string) => {
      const next = clearOwnerSession();
      setGeneration(next);
      clearPrivateCache(queryClient);
      resetEverywhere();
      setErrorMessage(reason ?? null);
      setStatus(
        profile === "private" || authRequired || demoLogin ? "signed-out" : "signed-in",
      );
      // The local session is already closed; a missing or expired server session is
      // equivalent to logout, so its failure must not reopen anything.
      void apiClient.endSession().catch(() => undefined);
    },
    [authRequired, demoLogin, profile, queryClient, resetEverywhere],
  );

  const enterDemo = useCallback(() => {
    beginOwnerSession();
    setErrorMessage(null);
    setGeneration(getSessionGeneration());
    setStatus("signed-in");
  }, []);

  const lock = useCallback(
    (message: string) => {
      signOut(message);
    },
    [signOut],
  );

  const signIn = useCallback(
    async (token: string): Promise<boolean> => {
      const trimmed = token.trim();
      if (trimmed.length === 0) return false;
      setErrorMessage(null);
      setStatus("checking");
      try {
        // The key is verified once and exchanged for an HttpOnly session cookie. It is
        // not retained here after this call returns.
        await apiClient.startSession(trimmed);
        setGeneration(getSessionGeneration());
        setStatus("signed-in");
        return true;
      } catch (error) {
        const next = clearOwnerSession();
        setGeneration(next);
        setStatus("signed-out");
        setErrorMessage(
          error instanceof ApiError && error.status === 503
            ? "Probation's owner sign-in is not configured yet. Check the backend setup and restart the app."
            : error instanceof Error
              ? error.message
              : "Could not sign in.",
        );
        return false;
      }
    },
    [],
  );

  const accountAuth = useCallback(
    async (
      authenticate: () => Promise<unknown>,
      email: string,
      password: string,
    ): Promise<boolean> => {
      if (!email.trim() || !password) return false;
      setErrorMessage(null);
      setStatus("checking");
      try {
        await authenticate();
        clearPrivateCache(queryClient);
        resetEverywhere();
        setGeneration(getSessionGeneration());
        setStatus("signed-in");
        return true;
      } catch (error) {
        const next = clearOwnerSession();
        setGeneration(next);
        setStatus("signed-out");
        setErrorMessage(
          error instanceof ApiError && error.code === "invalid_credentials"
            ? "That email and password do not match. Try again."
            : error instanceof ApiError && error.code === "account_exists"
              ? "An account already uses this email. Sign in instead."
              : error instanceof ApiError && error.code === "invalid_account_input"
                ? "Enter a valid email and a password of at least 8 characters."
                : error instanceof Error
                  ? error.message
                  : "Could not sign in.",
        );
        return false;
      }
    },
    [queryClient, resetEverywhere],
  );

  const signInAccount = useCallback(
    (email: string, password: string) =>
      accountAuth(() => apiClient.loginAccount(email.trim(), password), email, password),
    [accountAuth],
  );

  const registerAccount = useCallback(
    (email: string, password: string) =>
      accountAuth(() => apiClient.registerAccount(email.trim(), password), email, password),
    [accountAuth],
  );

  const value = useMemo<OwnerSessionValue>(
    () => ({
      profile,
      authRequired,
      demoLogin,
      status,
      generation,
      errorMessage,
      bootstrapError,
      loadBootstrap,
      enterDemo,
      signIn,
      signInAccount,
      registerAccount,
      signOut,
      lock,
    }),
    [authRequired, bootstrapError, demoLogin, enterDemo, errorMessage, generation, loadBootstrap, lock, profile, registerAccount, signIn, signInAccount, signOut, status],
  );

  return <OwnerSessionContext.Provider value={value}>{children}</OwnerSessionContext.Provider>;
}

export function useOwnerSession(): OwnerSessionValue {
  const context = useContext(OwnerSessionContext);
  if (context === null) throw new Error("useOwnerSession must be used inside OwnerSessionProvider");
  return context;
}

/** True only while this exact session generation is still the current one. */
export function useSessionGuard(): (generation: number) => boolean {
  const { generation } = useOwnerSession();
  const latest = useRef(generation);
  useEffect(() => {
    latest.current = generation;
  }, [generation]);
  return useCallback((candidate: number) => candidate === latest.current, []);
}
