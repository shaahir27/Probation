# Full-product planning coverage

Date: 22 October 2026. This records planning traceability, not implementation completion or a proof that every original allegation is true.

## Inputs and integrity

- `changes.md` SHA-256: `5ac47ff82e5082c7dc45cd486ba2a284fc92f9fa7a87d7a1adcd6fcd01eb496e`.
- Source lines: **333**, each represented once as `CH-Lnnnn`.
- Content-bearing source rows: **221**; remaining rows are explicitly classified headings, blanks or formatting.
- Additional opinion assertions: **23**, reviewed as O01-O23.
- Full-product capability IDs: **42**, all mapped by at least one register row.
- Unassigned source lines: **0**. Unassigned opinion assertions: **0**. Unknown feature targets: **0**.

## Artifacts

- [Implementation sequence](../CHANGES_IMPLEMENTATION_PLAN.md)
- [Full specification and F01-F42 acceptance](../FULL_PRODUCT_SPEC.md)
- [Opinion review](../PRODUCT_OPINION_REVIEW.md)
- [Complete source/opinion register](changes-coverage.csv)
- [Dated verification evidence](changes-audit-2026-10-22.md)

## What coverage means

Each source line has a disposition and one or more delivery requirements. Content rows use explicitly reviewed line-to-feature mappings against the pinned input hash; headings and formatting use section context. A line can contain multiple sentences or related tasks; the associated feature contract covers its subject matter. The register is deliberately inclusive of context and formatting so no text is silently omitted. Numeric experiment claims retain their source/audit status rather than becoming new measurements.

All F rows are required in the full profile, including Reading, every named connector, runtimes, signed receipts, NVIDIA dataset integration and the actual approved study. A provider or governance blocker remains open; it is not a silent feature cut. Unsupported universal claims are corrected in the opinion/audit rather than promised.

## Source row classes

| Class | Rows |
|---|---:|
| blank | 81 |
| format | 7 |
| heading | 24 |
| list_item | 118 |
| paragraph | 34 |
| reproduction_command | 4 |
| table_row | 65 |

## Release check

Before implementing a slice, verify the input hash and resolve its governing decisions. Before declaring full completion, replace planning status with accepted implementation/run evidence per F row, run the original core V cases and all connector/extension acceptance suites, and review every corrected/unverified claim. A zero-unassigned register establishes coverage only; it does not establish perfect code, actual account access or successful performance targets.
