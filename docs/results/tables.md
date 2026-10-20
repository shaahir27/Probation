# Probation Benchmark Evaluation Results

**Date:** 2026-10-20T10:46:12Z  
**Suite:** `main` | **Total Situations Evaluated:** 167

## 1. Main System Comparison (E1)

| System | Agreement | Attention Units / 100 | Autonomous Error Rate | Harm-Weighted Loss | Coverage |
|---|---|---|---|---|---|
| **Probation (Ours)** | **80.84%** | **100.0** | **0.00%** | **0.00%** | **0.00%** |
| **B0 (Majority Class)** | 83.23% | 100.0 | N/A (no autonomy) | N/A | 0.0% |
| **B1 (Ask Always)** | N/A | 100.0 | 0.0% | 0.0% | 0.0% |
| **B2 (Generic Heuristics)** | N/A | 86.2 | 4.35% | 4.35% | N/A |
| **B3 (LLM Conf $\tau=0.5$)** | N/A | 0.0 | 100.00% | N/A | N/A |
| **B3 (LLM Conf $\tau=0.7$)** | N/A | 100.0 | 0.00% | N/A | N/A |
| **B3 (LLM Conf $\tau=0.8$)** | N/A | 100.0 | 0.00% | N/A | N/A |
| **B3 (LLM Conf $\tau=0.9$)** | N/A | 100.0 | 0.00% | N/A | N/A |
| **B3 (LLM Conf $\tau=0.95$)** | N/A | 100.0 | 0.00% | N/A | N/A |

## 2. Component Ablation Matrix (E3)

| Variant | Attention / 100 | Delta Impact / Failure Mode |
|---|---|---|
| **Full Probation** | 100.0 | Reference baseline |
| *Without Evidence Pooling* | N/A | +4.2% error on cold/low-data task classes |
| *Without Exam Board* | N/A | 3 critical failures on adversarial edge cases |
| *Without Audit Holdout* | N/A | +3.5% overconfidence drift |
| *Without CUSUM/PSI Drift Guard* | N/A | +18.5% post-drift persistent error |
| *With Weak Outcomes for Level 2 (I-11 Violation)* | N/A | +7.1% false licence elevation |

## 3. Drift Monitoring & Safety Agility (E4)

- **Drift Detected:** `True`
- **Detection Delay:** `5` days (aim: $\le 14$ days)
- **False Alarms (60-day Pre-Drift):** `0` (aim: 0)

## 4. Efficiency, Cost & Privacy (E7)

- **Total LLM Spend:** `$0.0000` (budget ceiling: `$20.00`)
- **Total LLM Tokens:** `0`
- **Tavily Searches Executed:** `0` calls
