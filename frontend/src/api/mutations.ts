/**
 * Mutation flow: review, bind, respond — and the conflict path.
 *
 * A decision is first bound by `POST /review` (which returns the exact payload hash
 * the owner is approving), then submitted once with a stable pre-created request ID.
 * A 409 never resends: the stored binding is dropped, so the owner must fetch the
 * current item, read it and confirm again.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ApiError, apiClient, conflictCode, newRequestId } from "./client";
import { invalidatePrivateData, queryKeys } from "./queries";
import { ReviewDecision } from "../components/queue/ReviewForm";
import { registerSessionReset } from "../auth/OwnerSession";

interface PendingReview {
  requestId: string;
  body: Record<string, unknown>;
  reviewedPayloadHash?: string;
}

/** Maps an owner decision onto the frozen v2 review payload. */
export function reviewPayload(decision: ReviewDecision): Record<string, unknown> {
  switch (decision.kind) {
    case "accept":
      return { version: "v2", response: "accept" };
    case "reject":
      return { version: "v2", response: "reject" };
    case "leave":
      return { version: "v2", response: "leave" };
    case "edit":
      return {
        version: "v2",
        response: "edit",
        edited_action: decision.editedAction,
        ...(decision.editedBody !== undefined ? { edited_body: decision.editedBody } : {}),
      };
    case "forward":
      return {
        version: "v2",
        response: "edit",
        edited_action: "FORWARD",
        forward_recipient: decision.forwardRecipient,
        ...(decision.introduction !== undefined ? { edited_body: decision.introduction } : {}),
      };
  }
}

const CONFLICT_COPY: Record<string, string> = {
  review_binding_changed:
    "This email changed since you opened it, so the version you reviewed is no longer current. Nothing was sent. Read the current version and decide again.",
  operation_reconciled:
    "An earlier attempt for this email is still being reconciled. Nothing was sent again.",
  initial_decision_already_recorded:
    "This email has already been answered. Nothing was sent again.",
  operation_restricted:
    "Probation is now blocked from doing this. Nothing was sent.",
  request_payload_conflict:
    "This request was already recorded with different details. Nothing was sent.",
  command_id_conflict:
    "This request was already recorded with different details. Nothing was sent.",
  action_not_undoable:
    "This action can no longer be undone or cancelled. Nothing was sent.",
  legacy_action_binding_unavailable:
    "This action has no reviewable binding, so Probation cannot undo it safely. Nothing was sent.",
  review_binding_mismatch:
    "Probation could not match your decision to the version you reviewed. Nothing was sent.",
  source_grant_mismatch:
    "This email does not belong to the signed-in account. Nothing was sent.",
};

export function conflictMessage(code: string): string {
  return CONFLICT_COPY[code] ?? "Probation could not confirm the current state of this email. Nothing was sent.";
}

interface ReviewFlowResult {
  busy: boolean;
  conflict: string | null;
  error: string | null;
  submit(proposalId: string, decision: ReviewDecision): Promise<string | null>;
  /** Forces a fresh review: the next submit re-reads and re-binds before responding. */
  refresh(): void;
  clearConflict(): void;
}

/**
 * One review flow per mounted surface. `onRecorded` receives the durable request ID
 * so the caller can show status truth ("accepted for processing", never "done").
 */
export function useReviewFlow(onRecorded: (requestId: string) => void): ReviewFlowResult {
  const client = useQueryClient();
  const pending = useRef(new Map<string, PendingReview>());
  const controllers = useRef(new Set<AbortController>());
  const [busy, setBusy] = useState(false);
  const [conflict, setConflict] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(
    () =>
      registerSessionReset(() => {
        controllers.current.forEach((controller) => controller.abort());
        controllers.current.clear();
        pending.current.clear();
        setBusy(false);
        setConflict(null);
        setError(null);
      }),
    [],
  );

  const run = useCallback(
    async (proposalId: string, decision: ReviewDecision): Promise<string | null> => {
      const body = reviewPayload(decision);
      const key = `${proposalId}:${JSON.stringify(body)}`;
      const record: PendingReview = pending.current.get(key) ?? { requestId: newRequestId("review"), body };
      pending.current.set(key, record);
      const controller = new AbortController();
      controllers.current.add(controller);
      setBusy(true);
      setError(null);
      setConflict(null);
      try {
        if (record.reviewedPayloadHash === undefined) {
          const review = await apiClient.reviewQueue(proposalId, record.body, controller.signal);
          record.reviewedPayloadHash = review.reviewed_payload_hash;
        }
        const receipt = await apiClient.respondQueue(
          proposalId,
          {
            ...record.body,
            request_id: record.requestId,
            reviewed_payload_hash: record.reviewedPayloadHash,
          },
          controller.signal,
        );
        pending.current.delete(key);
        onRecorded(receipt.request_id);
        invalidatePrivateData(client);
        return receipt.request_id;
      } catch (reason) {
        const code = conflictCode(reason);
        if (code !== null) {
          // A conflict invalidates the binding: it must be re-reviewed and re-confirmed.
          pending.current.delete(key);
          // The list must refresh, but the item read must NOT: refetching here drops the
          // detail back to its loading state, which unmounts the conflict message the owner
          // is still reading and makes a screen reader announce it again. The binding is
          // invalidated locally instead, and "Review it again" fetches a fresh one.
          void client.invalidateQueries({ queryKey: queryKeys.queue });
          setConflict(conflictMessage(code));
        } else if (reason instanceof ApiError && (reason.code === "aborted" || reason.code === "session_changed")) {
          // Cancelled by logout: keep no state and show nothing.
        } else {
          pending.current.delete(key);
          setError(reason instanceof Error ? reason.message : "Your choice could not be sent.");
        }
        return null;
      } finally {
        controllers.current.delete(controller);
        setBusy(false);
      }
    },
    [client, onRecorded],
  );

  const refresh = useCallback(() => {
    pending.current.clear();
    setConflict(null);
  }, []);

  return { busy, conflict, error, submit: run, refresh, clearConflict: () => setConflict(null) };
}

// Split out so the review call can be cached per proposal without a stale binding.

/**
 * Administrative intents (dismiss a learned pattern, request a test). Each attempt
 * keeps one stable request ID so a double click cannot queue a second command, and a
 * 202 is reported as queued, never as completed.
 */
export function useAdminCommandFlow() {
  const pending = useRef(new Map<string, string>());
  const [submitted, setSubmitted] = useState<Array<{ localId: string; commandId: string }>>([]);
  const [error, setError] = useState<string | null>(null);
  const [busyKey, setBusyKey] = useState<string | null>(null);

  useEffect(
    () =>
      registerSessionReset(() => {
        pending.current.clear();
        setSubmitted([]);
        setError(null);
        setBusyKey(null);
      }),
    [],
  );

  const submit = useCallback(
    async (kind: "deny-habit" | "run-exam", target: string, run: (requestId: string) => Promise<{ command: { id: string } }>) => {
      const key = `${kind}:${target}`;
      const requestId = pending.current.get(key) ?? newRequestId(kind);
      pending.current.set(key, requestId);
      setBusyKey(key);
      setError(null);
      try {
        const result = await run(requestId);
        pending.current.set(key, result.command.id);
        setSubmitted((current) =>
          current.some((entry) => entry.commandId === result.command.id)
            ? current
            : [...current, { localId: requestId, commandId: result.command.id }],
        );
        return result.command.id;
      } catch (reason) {
        pending.current.delete(key);
        setError(reason instanceof Error ? reason.message : "Probation could not record this request.");
        return null;
      } finally {
        setBusyKey(null);
      }
    },
    [],
  );

  return { submitted, error, busyKey, submit };
}

/** Undo/cancel intent with one stable request ID per attempt. */
export function useUndoFlow(onRecorded: (requestId: string) => void) {
  const client = useQueryClient();
  const pending = useRef(new Map<string, string>());
  const controllers = useRef(new Set<AbortController>());
  const [busyId, setBusyId] = useState<string | null>(null);
  const [conflict, setConflict] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(
    () =>
      registerSessionReset(() => {
        controllers.current.forEach((controller) => controller.abort());
        controllers.current.clear();
        pending.current.clear();
        setBusyId(null);
        setConflict(null);
        setError(null);
      }),
    [],
  );

  const undo = useCallback(
    async (actionId: string): Promise<string | null> => {
      const requestId = pending.current.get(actionId) ?? newRequestId("undo");
      pending.current.set(actionId, requestId);
      const controller = new AbortController();
      controllers.current.add(controller);
      setBusyId(actionId);
      setError(null);
      setConflict(null);
      try {
        await apiClient.undoAction(actionId, requestId, controller.signal);
        pending.current.delete(actionId);
        onRecorded(requestId);
        void client.invalidateQueries({ queryKey: queryKeys.actions });
        return requestId;
      } catch (reason) {
        const code = conflictCode(reason);
        if (code !== null) {
          pending.current.delete(actionId);
          setConflict(conflictMessage(code));
        } else if (reason instanceof ApiError && (reason.code === "aborted" || reason.code === "session_changed")) {
          // Cancelled by logout: keep no state and show nothing.
        } else {
          pending.current.delete(actionId);
          setError(reason instanceof Error ? reason.message : "The action could not be undone.");
        }
        return null;
      } finally {
        controllers.current.delete(controller);
        setBusyId(null);
      }
    },
    [client, onRecorded],
  );

  return { busyId, conflict, error, undo };
}
