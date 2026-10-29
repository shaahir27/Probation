import { useState } from "react";
import { apiClient } from "../../api/client";
import type { DemoAnalyzeResponse } from "../../api/types";
import { Button } from "../common/Button";

const ANALYZE_SAMPLE =
  "Subject: Renewal due\n\nPlease renew the club membership by Friday. If it lapses we will close the order.";

function money(value: number): string {
  return `$${value.toFixed(4)}`;
}

/** One real reader call, with the redaction counts and the accounting it bought. */
export function LiveModelCard() {
  const [text, setText] = useState(ANALYZE_SAMPLE);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<DemoAnalyzeResponse | null>(null);

  const submit = async () => {
    if (busy || text.trim().length === 0) return;
    setBusy(true);
    setError(null);
    try {
      setResult(await apiClient.demoAnalyze(text));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "That call could not complete.");
    } finally {
      setBusy(false);
    }
  };

  const scalarEntries =
    result === null
      ? []
      : Object.entries(result.result).filter(
          ([, value]) =>
            value === null || ["string", "number", "boolean"].includes(typeof value),
        );
  const redactions =
    result === null
      ? []
      : Object.entries(result.redaction_counts).map(([kind, count]) => `${count} ${kind}`);

  return (
    <section className="live-model-card" aria-labelledby="live-analysis-title" data-ui="live-model-card">
      <div className="live-model-intro">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 id="live-analysis-title" className="font-serif text-[24px] font-normal tracking-[-0.015em]">
            Try it live
          </h2>
          <span className="rounded-full border border-line px-2 py-0.5 text-[11px] font-semibold text-ink-secondary">
            Synthetic demo
          </span>
        </div>
        <p className="mt-2 max-w-[54ch] text-sm leading-6 text-ink-secondary">
          One real reader call to the configured Nemotron model through the same budget guard as
          production. The text is redacted before it reaches the model; identical text is served
          from the recorded answer at no cost.
        </p>
        <label className="mt-4 block text-sm">
          <span className="text-ink-secondary">Email text to analyse</span>
          <textarea
            value={text}
            onChange={(event) => setText(event.target.value)}
            maxLength={4000}
            rows={5}
            className="mt-2 w-full rounded-lg border border-line bg-canvas p-3 text-[13px] leading-6"
          />
        </label>
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <Button variant="secondary" size="md" disabled={busy || text.trim().length === 0} onClick={() => void submit()}>
            {busy ? "Asking the model…" : "Analyse this email"}
          </Button>
          <span className="text-xs text-ink-tertiary">{text.length} / 4000 characters</span>
        </div>
        {error !== null && <p role="alert" className="mt-3 text-sm text-status-danger">{error}</p>}
      </div>

      <div className="live-model-output">
        {result === null ? (
          <>
            <h3>What happens in the call</h3>
            <ol className="live-model-steps">
              <li><strong>Redact.</strong> Names, addresses and account tokens are masked before anything leaves this machine.</li>
              <li><strong>Read.</strong> The registered reader returns a strict structured form: intent, deadline, money, urgency and risk.</li>
              <li><strong>Record.</strong> The model, tokens, latency and this call's cost are recorded, never the raw text.</li>
            </ol>
            <p className="live-model-note mt-4">The result appears here. This is a read, not a recommendation.</p>
          </>
        ) : (
          <>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="text-sm">
                <span className="text-ink-tertiary">Model</span>{" "}
                <span className="break-words font-mono text-xs">{result.model}</span>
              </p>
              <span className="rounded-full border border-line px-2 py-0.5 text-[11px] font-semibold text-ink-secondary">
                {result.cached ? "Recorded answer" : "Live call"}
              </span>
            </div>
            <dl className="live-model-metrics mt-4">
              <div><dt>Tokens in</dt><dd>{result.tokens_in}</dd></div>
              <div><dt>Tokens out</dt><dd>{result.tokens_out}</dd></div>
              <div><dt>Latency</dt><dd>{result.latency_ms} ms</dd></div>
              <div><dt>This call</dt><dd>{money(result.usd)}</dd></div>
            </dl>
            {redactions.length > 0 && <p className="live-model-note mt-3">Masked before the model: {redactions.join(", ")}.</p>}
            {result.cached && <p className="live-model-note mt-1">Cached: this repeated input made no new paid call.</p>}
            {scalarEntries.length > 0 && (
              <dl className="mt-3 divide-y rounded-lg border border-line text-sm">
                {scalarEntries.map(([key, value]) => (
                  <div key={key} className="flex flex-wrap items-baseline justify-between gap-2 p-2">
                    <dt className="text-ink-secondary">{key.replace(/_/g, " ")}</dt>
                    <dd className="break-words font-mono text-xs">{String(value)}</dd>
                  </div>
                ))}
              </dl>
            )}
            <p className="live-model-note mt-3">
              This is a read, not a recommendation.{" "}
              <a href="#/queue" className="underline underline-offset-4">Review</a> shows the recorded recommendation and its evidence.
            </p>
          </>
        )}
      </div>
    </section>
  );
}
