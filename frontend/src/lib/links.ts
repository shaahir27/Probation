/**
 * The one place an outbound URL is decided.
 *
 * Source links and board entries arrive as untrusted strings. Only absolute
 * http(s) URLs are ever rendered as a link; anything else (script:, data:,
 * javascript:, a bare word) becomes plain text, so no label can become an
 * executable URL. Text is rendered through React, which escapes it; raw item or
 * page HTML is never rendered.
 */

const ALLOWED_PROTOCOLS = new Set(["http:", "https:"]);

/** Returns a safe absolute URL string, or null when the value is not linkable. */
export function safeExternalUrl(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const candidate = value.trim();
  if (candidate.length === 0 || candidate.length > 2048) return null;
  let parsed: URL;
  try {
    parsed = new URL(candidate);
  } catch {
    return null;
  }
  if (!ALLOWED_PROTOCOLS.has(parsed.protocol)) return null;
  if (!parsed.hostname) return null;
  return parsed.toString();
}

/** Human label for a citation; never trusted as markup and never the URL by default. */
export function linkLabel(title: unknown, url: string): string {
  if (typeof title === "string" && title.trim().length > 0) return title.trim();
  return url;
}

/** Domain shown beside a citation so the owner can see who is being claimed. */
export function linkOrigin(url: string): string {
  try {
    return new URL(url).hostname;
  } catch {
    return "source unavailable";
  }
}

/**
 * Email address check for the forward recipient field. The server re-validates
 * against the owner's allow-list; this only stops an obviously unusable value
 * and CRLF injection from leaving the browser.
 */
export function isValidEmailCandidate(value: string): boolean {
  const candidate = value.trim();
  if (candidate.length === 0 || candidate.length > 320) return false;
  if (/[\r\n]/.test(candidate)) return false;
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(candidate);
}
