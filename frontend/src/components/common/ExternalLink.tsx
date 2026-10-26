import { linkLabel, linkOrigin, safeExternalUrl } from "../../lib/links";

interface ExternalLinkProps {
  url: unknown;
  title?: unknown;
  className?: string;
  /** Adds the source domain after the label so the owner sees who is claimed. */
  showOrigin?: boolean;
}

/**
 * The only outbound anchor in the app. A value that is not absolute http(s)
 * renders as plain text with an explicit reason, so an untrusted or malformed
 * source never becomes a clickable link.
 */
export function ExternalLink({ url, title, className = "", showOrigin = true }: ExternalLinkProps) {
  const href = safeExternalUrl(url);
  if (href === null) {
    return (
      <span className={`text-ink-tertiary ${className}`.trim()}>
        Source link unavailable
      </span>
    );
  }
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer nofollow"
      className={`underline underline-offset-4 break-words ${className}`.trim()}
    >
      {linkLabel(title, href)}
      {showOrigin ? <span className="text-ink-tertiary"> ({linkOrigin(href)})</span> : null}
      <span className="sr-only"> (opens in a new tab)</span>
    </a>
  );
}
