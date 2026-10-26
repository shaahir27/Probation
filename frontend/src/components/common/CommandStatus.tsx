import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useCommandRead } from "../../api/queries";
import { registerSessionReset } from "../../auth/OwnerSession";

const COPY: Record<string, string> = {
  PENDING: "Your request is queued. Probation is still processing it.",
  SUCCEEDED: "Your request completed.",
  FAILED: "A request failed. Its changes were not confirmed.",
};

/**
 * Durable admin command status. A queued command is never shown as completed, and
 * the list clears itself with the session so a new sign-in cannot see another
 * session's requests.
 */
export function CommandStatus({ commandIds, onSettled }: { commandIds: string[]; onSettled: () => void }) {
  if (commandIds.length === 0) return null;
  return (
    <ul className="mb-4 space-y-2">
      {commandIds.map((id) => (
        <CommandRow key={id} id={id} onSettled={onSettled} />
      ))}
    </ul>
  );
}

function CommandRow({ id, onSettled }: { id: string; onSettled: () => void }) {
  const client = useQueryClient();
  const read = useCommandRead(id, true);
  const status = read.data?.command.status ?? null;

  useEffect(
    () => registerSessionReset(() => client.removeQueries({ queryKey: ["private", "command", id] })),
    [client, id],
  );

  useEffect(() => {
    if (status === "SUCCEEDED" || status === "FAILED") onSettled();
  }, [onSettled, status]);

  const message =
    status !== null
      ? COPY[status] ?? "The request status is unavailable."
      : read.error !== null
        ? "The request status is unavailable. The request may still be pending."
        : "Your request is queued. Probation is still processing it.";

  return (
    <li role="status" aria-live="polite" className="rounded-xl border border-line bg-surface p-4 text-sm">
      {message}
    </li>
  );
}
