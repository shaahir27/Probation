/** Presentation helpers for engine summaries. The API keeps the full text; the UI shows a
 * subject, a short preview and the body without the sender's legal disclaimer wall. */

const DISCLAIMER = /(?:\s|^)(?:-{2,}\s*)?::DISCLAIMER::?/i;
const URL_TOKEN = /<<URL:[^>]*>>/gi;

function compact(value: string): string {
  return value.replace(URL_TOKEN, " ").replace(/-{4,}/g, " ").replace(/\s+/g, " ").trim();
}

export interface EmailText {
  subject: string;
  preview: string;
  body: string;
  disclaimer: string | null;
}

export function parseEmailText(summary: string | null | undefined): EmailText {
  const raw = (summary ?? "").replace(/\r\n/g, "\n").trim();
  if (!raw) {
    return { subject: "Email details unavailable", preview: "", body: "", disclaimer: null };
  }

  const subjectMatch = raw.match(/^\s*Subject:\s*([^\n]*)/i);
  let subject = subjectMatch ? subjectMatch[1].trim() : (raw.split("\n")[0] ?? "").trim();
  let body = subjectMatch
    ? raw.slice(subjectMatch[0].length).replace(/^\s*\n?/, "")
    : raw.split("\n").slice(1).join("\n");

  const subjectDisclaim = subject.search(DISCLAIMER);
  if (subjectDisclaim >= 0) subject = subject.slice(0, subjectDisclaim).trim();
  if (subject.length > 140) subject = `${subject.slice(0, 139).trimEnd()}…`;

  let disclaimer: string | null = null;
  const split = body.search(DISCLAIMER);
  if (split >= 0) {
    const marker = body.slice(split).match(DISCLAIMER)?.[0] ?? "";
    disclaimer = compact(body.slice(split + marker.length));
    body = body.slice(0, split).trim();
  }

  body = body
    .replace(URL_TOKEN, "")
    .replace(/\n{3,}/g, "\n\n")
    .replace(/[ \t]+\n/g, "\n")
    .trim();
  const previewSource = compact(body);
  const preview =
    previewSource.length > 176
      ? `${previewSource.slice(0, 176).replace(/\s+\S*$/, "").trimEnd()}…`
      : previewSource;

  return {
    subject: subject || "Email details unavailable",
    preview,
    body,
    disclaimer,
  };
}

export function senderDisplay(value: string | null | undefined): string {
  const raw = (value ?? "").trim();
  if (!raw || !raw.includes("@")) return raw || "Sender unavailable";
  const [local, domain] = raw.split("@");
  if (local.length <= 22) return raw;
  return `${local.slice(0, 16)}…@${domain}`;
}

export function formatWhen(value: string | null | undefined): string {
  if (!value) return "Not recorded";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}
