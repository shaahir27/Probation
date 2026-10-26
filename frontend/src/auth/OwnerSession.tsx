/**
 * Owner session: the memory-only credential boundary for the private workspace.
 *
 * The key exists only as React state plus the in-memory bearer value inside
 * `api/client.ts`. It is never written to a URL, browser storage, a query key, a
 * log line or an env var. Logout is safe by construction: it bumps a monotonic
 * session generation, aborts every in-flight request, clears the cached private
 * data, and asks every registered panel to drop drafts and review bindings.
 */

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ApiError, apiClient, clearOwnerToken, getSessionGeneration, installOwnerToken } from "../api/client";
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
  status: SessionStatus;
  generation: number;
  /** Message from the last failed attempt; null once a read succeeds. */
  errorMessage: string | null;
  bootstrapError: string | null;
  loadBootstrap(): Promise<void>;
  signIn(token: string): Promise<boolean>;
  signOut(reason?: string): void;
  /** Called by any read that returned 401/403 so the UI fails closed. */
  lock(message: string): void;
}

const OwnerSessionContext = createContext<OwnerSessionValue | null>(null);

export function OwnerSessionProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [profile, setProfile] = useState<Profile | null>(null);
  const [authRequired, setAuthRequired] = useState(false);
  const [status, setStatus] = useState<SessionStatus>("unknown");
  const [generation, setGeneration] = useState(0);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [bootstrapError, setBootstrapError] = useState<string | null>(null);
  const tokenRef = useRef<string | null>(null);

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
      setStatus(value.auth_required ? "signed-out" : "signed-in");
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
      tokenRef.current = null;
      const next = clearOwnerToken();
      setGeneration(next);
      clearPrivateCache(queryClient);
      resetEverywhere();
      setErrorMessage(reason ?? null);
      setStatus(profile === "private" || authRequired ? "signed-out" : "signed-in");
    },
    [authRequired, profile, queryClient, resetEverywhere],
  );

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
      installOwnerToken(trimmed);
      tokenRef.current = trimmed;
      try {
        // A real read proves the credential; nothing is marked signed-in on a form submit alone.
        await apiClient.getQueue();
        setGeneration(getSessionGeneration());
        setStatus("signed-in");
        return true;
      } catch (error) {
        clearOwnerToken();
        tokenRef.current = null;
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

  const value = useMemo<OwnerSessionValue>(
    () => ({
      profile,
      authRequired,
      status,
      generation,
      errorMessage,
      bootstrapError,
      loadBootstrap,
      signIn,
      signOut,
      lock,
    }),
    [authRequired, bootstrapError, errorMessage, generation, loadBootstrap, lock, profile, signIn, signOut, status],
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
