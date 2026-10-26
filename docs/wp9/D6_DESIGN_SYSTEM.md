# D6 Interface Design

## Direction

Use the existing Spruce & Brass palette and typographic roles. Follow the Taste Skill app-screen workflow and UI UX Pro Max React/Tailwind guidance. Prefer a quiet, opaque, dark work surface with readable hierarchy, one primary next action per screen, and a compact list/detail layout. Avoid decorative gradients, glowing tiles, vanity trust scores, redundant panels, and jargon in primary views.

Keep fonts local/system; remove remote font loading. Do not add a new design library or router for this pass.

## Main navigation

Home · Review · Actions · Permissions · More

Watching is a separate view from Review, linked from Home and Review. More contains only working or truthfully unavailable secondary destinations.

Use real links and browser history. On small screens, detail is a separate route with working Back navigation. Keep filters in the URL. Unknown routes have a clear not-found state.

## Screen rules

- Home: one sentence for what Probation is doing, current readiness, and one useful next action.
- Review: actual unanswered items, clear recommendation, reason, evidence, and supported decision controls.
- Watching: items for which the system is observing or waiting; never imply an action is awaiting approval if it is not.
- Detail: source, requested action, verified facts with citations/status, expiry, and “Why” / “Details” disclosure.
- Actions: actual operation state, what happened, and whether undo is supported now.
- Permissions: explain what the system may do and what evidence/restrictions currently apply; never imply a user-editable licence.
- More: actual data or an explicit unavailable/unsupported explanation.

## Accessibility and responsive behavior

Support keyboard navigation, visible focus, semantic landmarks, announced field errors, reduced motion, 200% zoom, high contrast, and at least 44px primary touch targets. Maintain readable line length and adequate spacing at 360–1440px widths. Use accessible dialogs only when a dialog is necessary; restore focus on close.

Every asynchronous panel has a labelled loading, empty, error, stale, locked, or unsupported state where applicable. Do not mark a queued operation complete.
