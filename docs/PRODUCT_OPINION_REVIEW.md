# Review of the additional product opinion

Date: 22 October 2026. Input: the opinion supplied in the user's request for a complete product plan. This document records dispositions of that opinion; it does not claim that a repaired application has been run.

Full delivery scope: [FULL_PRODUCT_SPEC.md](FULL_PRODUCT_SPEC.md). Implementation sequence: [CHANGES_IMPLEMENTATION_PLAN.md](CHANGES_IMPLEMENTATION_PLAN.md). Original audit evidence: [changes-audit-2026-10-22.md](reports/changes-audit-2026-10-22.md).

## Assertion-by-assertion disposition

| ID | Opinion assertion or proposal | Assessment | Requirement carried into the full plan |
|---|---|---|---|
| O01 | Mostly covers the core, not everything previously claimed | Supported description of the earlier plan's scope | Full completion now requires the complete F01-F42 register; a core-only release is labelled partial. |
| O02 | The writer has not run the fixed version | Correct limitation to retain | There is no completed fixed version established by this review. Existing baseline checks do not prove future repairs. |
| O03 | Connects accounts, learns decisions, predicts and earns autonomy | Intended product behavior, not a demonstrated outcome | Gmail, Google Calendar, local files, Notion, IMAP, iCal, MCP client/server and always-on runtime have explicit delivery/acceptance contracts. |
| O04 | Every action remains undoable or cancellable | Too broad | Every supported action has declared reversibility. A hold can be cancelled before effect; a sent reply or transmitted RSVP cannot generally be recalled. UI and README must distinguish these states. |
| O05 | Learns repeated decisions, not general knowledge of how someone works | Correct scope | Define observable families/features and limit explanations to actual footprints. No claim of unrestricted workplace intelligence. |
| O06 | Does not observe screens or keystrokes | Contractual requirement | Static/runtime boundary tests; no screen, keyboard or click recording dependency. |
| O07 | Own accounts with consent; not monitoring other people | Required product scope | Single owner, selected resources, separate connection/observation/execution grants and revocation. Ordinary messages from others in the owner's mailbox are protected input, not another account to monitor. |
| O08 | This is safer legally and better aligned with the track | Opinion, not a legal conclusion or a guaranteed judging result | Document the design and obtain applicable provider/participant approvals. Do not claim legal compliance or a prize from this statement. |
| O09 | Roughly 58 matches for 95%, 148 for 98%, plus exam | Correct only for the no-parent, zero-failure Beta(1,1) examples | Also enforce strong/raw/recent minimums, pooling, action cap, exam validity, drift/family alarms, novelty and economics. The UI must show actual required evidence, not a fixed countdown to 58. |
| O10 | New accounts mostly Watch/Suggest initially | Reasonable expectation, not a promise of promotion | Cold-start state and missing-history explanations; no forced confidence or seven-day automatic unlock. |
| O11 | Backfill past mail and Sent to show earned live autonomy | Useful but requires a temporal-evidence policy | Separate historical replay, import-time snapshots and prospective live commitments. Backfill cannot recover unavailable label-change history or pretend a proposal was committed before an already existing outcome. |
| O12 | Replies/RSVPs never silent and always get hold/cancel | First part matches current cap 2; “always” needs correction | Autonomous level-2 non-recallable operations hold. Explicit accept/edit currently executes immediately under CONTRACT section 8. Do not add an unconditional hold without a human contract change. |
| O13 | Performance targets may fail | Correct | Evaluate interrupted attention at matched error, promotion latency and cheating-policy detection with counts and uncertainty; publish failures/unsupported samples. |
| O14 | Majority baseline is already about 90% because of archive imbalance | Specific earlier audit observation; not verified as a universal/current result | Compute B0 chronologically for each dataset/family; report class imbalance and non-no-op coverage. Never carry a historical 90% into new results as a constant. |
| O15 | Lead with interruptions at matched error rather than accuracy alone | Good evaluation framing, subject to measured feasibility | Show risk/coverage/attention curves, abstentions, denominators and the lowest attainable error if a method misses the selected target. |
| O16 | Cut Reading, OpenShell, human study and Personas-India | Rejected for this full-scope request | Retain all four as explicit work packages and release evidence. The user's latest no-cut scope supersedes the earlier deadline-based cut recommendation. |
| O17 | None of those four exists in the repo | Inaccurate as a blanket statement | Reading modules/registration, human-study simulation code and sandbox documentation already exist. A real integration/study is not established by their presence. The current persona module builds local personas; NVIDIA dataset ingestion remains to be built/verified. |
| O18 | README: learns own footprints | Claim permitted after acceptance evidence | Show input types and a source-linked synthetic/live-local example; distinguish private deployment from public synthetic demo. |
| O19 | README: permission per task with evidence | Claim permitted after lifecycle verification | Exact class/action counts, lower bound, cap, exam date and alarm handling agree across API and Executor. |
| O20 | README: no irreversible action without hold or undo | Rewrite to precise supported behavior | “Autonomous sends and RSVPs have a cancellation window before execution. Reversible actions support undo within the displayed window. Explicit approval may execute immediately.” Do not promise post-send recall. |
| O21 | README: web facts add caution only | Contractual for entity facts; needs content distinction | Entity facts never raise probabilities/evidence/licences. Quarantined content clues for a user-saved Reading item are the documented separate permitted case. |
| O22 | README: corrected measurements including negative results | Required | Commit reproducible aggregate evidence/provenance, with unavailable rates for empty samples and no fabricated ablations. |
| O23 | A smaller claim will survive scrutiny | Sensible communication advice; size is not a correctness proof | Implement the full requested scope, but publish only individually demonstrated claims. An incomplete milestone is not called fully complete. |

## Numerical and action examples

Under the no-parent, zero-failure case in `docs/ENGINE_SPEC.md` sections 6.2 and 16:

`LB = 0.05 ** (1 / (n + 1))`.

This gives the 58/148 golden thresholds. A parent prior, any disagreement, evidence aging, insufficient recent strong cases or an invalid exam changes qualification. The thresholds do not guarantee that a policy's individual prediction passes the economic/novelty/cap checks.

The supported action timeline must distinguish:

1. Suggested reply → explicit owner approval → immediate send → sent, cannot recall.
2. Autonomous level-2 reply → HELD → cancellation before deadline or one send after fresh checks → sent, cannot recall.
3. Reversible file/archive/track action → DONE → undo within its allowed window, subject to conflict-safe restoration.

No copy should say that all operations remain reversible forever. Payment, application submission, document sharing, permanent destructive operations and surveillance do not become allowed because the user requested a complete product.

## Effect on planning

The full plan retains the opinion's limited-learning model, consent, conservative authority and honest evaluation. It corrects unconditional undo/hold and threshold claims. It does not apply the suggested feature cuts. Source-level traceability for `changes.md` is separate from this O01-O23 opinion register; both must have no unassigned requirements before release.
