# NVIDIA OpenShell Sandbox Spike & Policy Specification

Authority: `docs/IMPLEMENTATION_PLAN.md` Phase 0 (Task: Sandbox spike, time-box 3 hours) and `docs/DECISIONS_AND_OPEN_QUESTIONS.md` O-4.

---

## 1. Objective

Explore running untrusted code or quarantining the `brain` and `examiner` workers inside an **NVIDIA OpenShell** container sandbox with a strict network egress allow-list.

## 2. Invariants & Network Boundary

Per `docs/CONTRACT.md`:
- `workers/brain.py` and `workers/examiner.py` MUST NOT have arbitrary network access.
- Network calls are restricted to:
  1. `llm/client.py` -> Nebius Token Factory endpoint (`api.tokenfactory.nebius.com:443`).
  2. `web/client.py` -> Tavily API (`api.tavily.com:443`).
  3. Pack connectors (MBOX, ICS, local filesystem).
  4. `workers/executor.py` -> Controlled write targets.

## 3. Spike Findings & Cut-Line Decision

1. **Local VM Portability**:
   - OpenShell requires specific Linux kernel eBPF modules and container capabilities that are non-trivial to provision across arbitrary developer workstations and small VM tiers.
2. **Time-Box Enforcement**:
   - Per `IMPLEMENTATION_PLAN.md` Phase 0 cut line: *"skip the sandbox spike if it exceeds 3 hours."*
3. **Architectural Mitigation**:
   - In place of a heavy kernel-level sandbox during development, Probation enforces security and network isolation via:
     - **Static Import Graph Checks (`T-SEC`, `T-WEBISO`)**: Automated pytest fixtures asserting that `brain` and `examiner` have zero imports of write credentials, execution functions, or web retrieval modules.
     - **Docker Compose Network Isolation**: Production deployment separates `backend` internal subnet from untrusted egress.

## 4. Policy Definition (Production Target)

When deploying with OpenShell on Nebius VM, the allow-list is defined as:
```yaml
policy:
  version: "1.0"
  network:
    default: "deny"
    allow:
      - host: "api.tokenfactory.nebius.com"
        port: 443
        protocol: "tcp"
      - host: "api.tavily.com"
        port: 443
        protocol: "tcp"
  filesystem:
    read_only:
      - "/app/src"
      - "/app/config"
    read_write:
      - "/app/data"
```
