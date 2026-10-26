# D6 Implementation Plan

## Objective

Connect the Gmail D4 and Nemotron/Tavily D5 work to a safe, understandable application. The demonstration must show actual API data and truthful processing states. It must not claim autonomy or execution where the engine has not earned or confirmed it.

## Verified base and isolation

- Branch: `phase-9-d6-api-frontend`
- Worktree: `data/d6/worktree`
- Base: `29f1f6616cdb08ee769a4f2bbad95b35e50f902d` (`origin/main`, 2026-10-25, `phase-6c: fix Gmail cohort filtering`)
- The existing root main worktree has two pre-existing staged `build_history` files. They are outside this branch and must remain unchanged.
- D4 and D5 worktrees are owned by their respective agents; do not modify or copy them.

## Shared contracts

Read `docs/wp9/D6_API_CONTRACT.md`, `docs/wp9/D6_DESIGN_SYSTEM.md`, and `docs/wp9/D6_COPY_DECK.md` before integrating parallel work. The root coordinator owns shared interfaces, dependency files, integration, and Git operations. Workers edit only their assigned paths.

## Work waves and ownership

1. Runtime agent: worker bootstrap, isolated role environments, Brain/Resolver/Examiner loops, Brain↔Webfacts IPC, snapshot extraction, runtime tests.
2. API agent: common owner authentication, protected API reads/writes, response models, canonical Gmail source identity, provenance, route and regression tests.
3. Frontend agent: same-origin authenticated API client, session/navigation, responsive app and review workflow, plain-language copy, accessibility, browser tests.
4. Coordinator after integration: durable replay controls and restart recovery, cross-layer fixtures/contracts, full integration, acceptance report.
5. Independent review, focused/final verification, local build-history report, phase handoff.

Do not edit `docs/CONTRACT.md`. A newly required authority or credential change is a contract-change request and stops that affected scope. Do not add a role writer for an unapproved table.

## Core sequence

Incoming Gmail → bounded HistoryView snapshot → configured Nemotron reader → isolated Webfacts verification where applicable → fresh restrictions and cutoff → existing gate and derived licence → durable proposal/draft → owner review → Executor-only side effect → Resolver observation → Examiner verdict.

Failures, cold start, unknown execution, and unsupported connector operations stay visible and fail closed. Tavily text remains quarantined and cannot raise autonomy. No mail-body URLs are fetched.

## Frontend acceptance

Apply Taste app-screen and UI UX Pro Max guidance while keeping the existing Spruce & Brass identity. Home has one clear next step. Review and Watching are distinct. Use everyday labels from `docs/wp9/D6_COPY_DECK.md`; explanations and technical evidence remain available under “Why” or “Details”. Every API resource has honest loading, empty, error, stale, locked, and unsupported states as applicable. Private credentials stay in memory and same-origin requests only.

## Budget and external effects

Keep the original cumulative ceiling: $1 Nebius and 20 Tavily credits, including prior charges and holds. Use the established D5 accounting authority and account identity. Paid checks are sequential and only after offline checks. Live Gmail writes require the exact operation manifest and explicit owner approval. Do not push, merge, or deploy in D6.

## Completion record

Create `docs/reports/phase-9-d6.md`, update local `build_history/` per protocol, preserve unrelated staged paths, and record exact test/effect evidence. D6 completion does not claim D7 accuracy or D8 public deployment/isolation.
