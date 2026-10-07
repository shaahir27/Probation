# Probation

> A personal AI that earns permission to act, one task type at a time, by proving on the user's own history that it would have done what they did.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-blue.svg)](https://www.python.org/)
[![Node 20+](https://img.shields.io/badge/Node-20%2B-green.svg)](https://nodejs.org/)

Built for the **NVIDIA Global AI Hackathon** (Personal AI Track) using **NVIDIA Nemotron** hosted on **Nebius Token Factory**, with **Tavily** web grounding for asymmetric entity verification and opportunity discovery.

---

## 1. Core Principle: Earned Autonomy

Probation bridges the delegation gap between "asking for everything" and "blind autonomous action".

Instead of trusting an LLM blindly or setting static rule trees:
1. **Walk-forward Backtesting**: Probation observes past user traces (`mail`, `calendar`, `files`, `chains`, `radar`, `reading`) under strict `HistoryView(as_of=t)` constraints (no peeking).
2. **Offline Shadow Prediction**: It records predictions *before* discovering the true user action.
3. **Statistical Evidence**: Per `(class, action)` pair, it computes a pessimistic lower-bound credibility score ($LB_{0.95}$) using Beta distributions with clipped empirical Bayes pooling.
4. **Trick-Question Examination Board**: Before an autonomous licence is issued, the policy must pass invariance and counterfactual exams.
5. **Dynamic Licences**:
   - **Level 0 (Watch)**: Silent shadow evaluation.
   - **Level 1 (Suggest)**: Visible suggestion queue for one-click human approval.
   - **Level 2 (Do with Undo)**: Autonomous execution held in an undo window.
   - **Level 3 (Do Silently)**: Immediate execution for low-risk, reversible actions.
6. **Automatic Demotion & Drift Detection**: Licences expire automatically and are demoted instantly on user override, undo burst, or habit drift (CUSUM / PSI).

---

## 2. Architecture & Invariants

- **LLMs Hold Data Only**: LLM outputs are strictly validated schema objects. LLMs never hold credentials or tools and never decide permissions.
- **Fail-Closed Gate**: Any validation error, budget exhaustion, or novelty spike triggers `ASK` or `SHADOW`.
- **Sole Execution Boundary**: Only `workers/executor.py` holds execution credentials and performs side effects.
- **Asymmetric Web Grounding (Tavily)**: Web facts can **only restrict autonomy or inform**, never raise autonomy ("The web can warn you; only your history can trust"). Quarantined extractors protect against prompt injection from untrusted web pages.
- **Tamper-Evident Ledger**: All audit trails, decisions, proposals, and licence changes are recorded in an append-only, SHA-256 hash-chained SQLite ledger.

---

## 3. Quickstart

### Prerequisites
- Python 3.11+
- Node.js 20+ & npm
- [Optional for live LLM / Web calls]: Nebius Token Factory API key, Tavily API key

### Setup
```bash
# Clone the repository
git clone https://github.com/your-username/probation.git
cd probation

# Copy environment variables
cp .env.example .env

# Run setup (creates backend venv, installs dependencies, builds frontend)
make setup
```

### Development Commands
```bash
# Run lint, typing, and test verification suite
make check

# Run tests with coverage
make test

# Start backend API (http://localhost:8000)
make serve

# Start frontend dashboard (http://localhost:5173)
make web

# Verify ledger hash chain integrity
make ledger-verify

# Check LLM token usage and budget
make budget
```

---

## 4. Documentation Suite

The complete architectural specifications live under [`docs/`](docs/):
- [`docs/CONTRACT.md`](docs/CONTRACT.md): Invariants and non-negotiable architectural boundaries.
- [`docs/ENGINE_SPEC.md`](docs/ENGINE_SPEC.md): Statistical formulas, gate logic, and drift algorithms.
- [`docs/DATA_MODEL.md`](docs/DATA_MODEL.md): SQLite schema and hash-chained ledger format.
- [`docs/PACKS_SPEC.md`](docs/PACKS_SPEC.md): Domain pack specifications.
- [`docs/TAVILY_AND_NEW_PACKS.md`](docs/TAVILY_AND_NEW_PACKS.md): Tavily grounding and Radar/Reading packs.
- [`docs/IMPLEMENTATION_PLAN.md`](docs/IMPLEMENTATION_PLAN.md): Phase-by-phase roadmap.
- [`docs/TEST_PLAN.md`](docs/TEST_PLAN.md): Verification catalog (`T-...` test suites).

---

## 5. License

MIT License. See [LICENSE](LICENSE) for details.
