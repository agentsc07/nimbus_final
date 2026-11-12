# Nimbus Experiment Verification and Provenance Status (N1–N10 & C1–C9)

**Document Purpose:** Complete audit and classification of Project Nimbus evaluation experiments N1 through N10 (Network & System) and C1 through C9 (Cloud Orchestrator & Bedrock) in accordance with Red-Team Addendum Section 7.  
**Baseline Git Commit:** `29f37e7540fe7d130c845d0139dff77d8f827e78`  
**Shared Execution Module:** `scripts/p4_shared.py` (restored and verified).

---

## 1. Network & System Experiments Audit (N1–N10)

| ID | Experiment Name | Requirement Tested | Evaluated Data Source | Status / Category | Reproducible Runner Command | Evidence Path |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **N1** | IISc Campus Field Traces | E4, FR-6 | *None*: `traces/iisc_*.csv` are labelled synthetic | **Not run** (no campus traces collected) | *N/A* | `traces/` |
| **N2** | Poisson Outage Model | E4 | Seeded synthetic sample (the traces hold one outage, too few to fit) | **Fixed** (`modelled`) | `python results/final/N2/run_n2.py` | `results/final/N2/` |
| **N3** | Network Degradation (analytical model; planned as trace replay) | FR-6, NFR-2 | Closed-form formulas over six hand-set profiles; no trace replayed, no system run | **Fixed** (`modelled`) | `python results/final/N3/run_n3.py` | `results/final/N3/` |
| **N4** | Duplicate and Replayed Messages | FR-8 | Synthetic messages to a live in-process `server.py` (127.0.0.1) | **Fixed** (`simulated`) | `python results/final/N4/run_n4.py` | `results/final/N4/` |
| **N5** | Selective Sharing | FR-11 | Seeded random events and leases against `MapState.affected_clusters` | **Fixed** (`simulated`) | `python results/final/N5/run_n5.py` | `results/final/N5/` |
| **N6** | Audit Replay Determinism | FR-20, NFR-6 | Seeded orchestrator scenario, two processes per seed | **Fixed** (`simulated`) | `python results/final/N6/run_n6.py` | `results/final/N6/` |
| **N7** | Security & Privacy Audit | NFR-5 | Static scan of the repository (IAM files, tracked source, manifest, WAN schemas) | **Fixed** (`static_audit`) | `python results/final/N7/run_n7.py` | `results/final/N7/` |
| **N8** | Fleet Scalability (cloud side) | NFR-3 | In-process orchestrator, stand-in model, synthetic arrivals (not MIMIC-IV) | **Fixed** (`mock_llm`) | `python results/final/N8/run_n8.py` | `results/final/N8/` |
| **N9** | Cost per Task | NFR-4 | C9's real-Bedrock call/token counts priced at list rates | **Fixed** (`modelled`) | `python results/final/N9/run_n9.py` | `results/final/N9/` |
| **N10**| Operator Console Validation (cloud side) | FR-21, FR-22 | Local in-process `server.py` (127.0.0.1); no deployed cloud, no edge | **Fixed** (`measured`, cloud acknowledgement only) | `python results/final/N10/run_n10.py --no-video` | `results/final/N10/` |

---

## 2. Cloud Experiments Provenance Audit (C1–C9)

*Note on Provenance & Commit Reconciliation:* Historical commit logs and raw evaluation artifacts in `results/final/` confirm that C1, C2, C3, C6, C7, C8, and C9 were evaluated against **real Amazon Bedrock (`apac.amazon.nova-lite-v1:0`)**, with `C1_deployed` evaluated against the live deployed AWS cloud in `ap-south-1`. Companion `_standin` and `_local` suites provide offline reproducible verification using deterministic rule-based stand-in models (`mock_llm`). C4 and C5 represent deterministic software measurements (`measured`).

*Disambiguation of Result Commits vs. Execution Base Commits:* `env.json` captures the baseline repository commit active when a test script began execution, whereas the Git commit that recorded and committed the verified experiment outputs into the repository is the **Result Commit**.
- **C1**: Result Commit `4c97ce3` (Execution Base in env.json: `485d898`)
- **C2**: Result Commit `a76c160` (Execution Base in env.json: `485d898`)
- **C3**: Result Commit `1c00f6f` (Execution Base in env.json: `485d898`)
- **C6**: Result Commit `485d898` (Execution Base in env.json: `9a80a4e`)
- **C7**: Result Commit `6c89d37` (Execution Base in env.json: `65892f6`)
- **C8**: Result Commit `65892f6` (Execution Base in env.json: `0489b22`)
- **C9**: Result Commit `0489b22` (Execution Base in env.json: `4c97ce3-dirty`)

| ID | Experiment Title | PRD Goal | Provenance / Category | Target / Environment | Model Used | Result Commit | Evidence Path |
| :--- | :--- | :--- | :--- | :--- | :--- | :---: | :--- |
| **C1** | Request Understanding | FR-13 | **Real Bedrock Execution** (`real_bedrock`) | Local server (`macOS arm64`) | `apac.amazon.nova-lite-v1:0` | `4c97ce3` | `results/final/C1/` |
| **C1_deployed** | Request Understanding (AWS) | FR-13 | **Real Bedrock Execution** (`real_bedrock`) | Deployed AWS API Gateway (`ap-south-1`) | `apac.amazon.nova-lite-v1:0` | `071bbc6` | `results/final/C1_deployed/` |
| **C1_standin** | Request Understanding (Offline) | FR-13 | **Local Simulation** (`mock_llm`) | Local server (`Linux x86_64`) | `rule-based-stand-in` | `071bbc6` | `results/final/C1_standin/` |
| **C2** | Rules & Shared Map | FR-17 | **Real Bedrock Execution** (`real_bedrock`) | Local server (`macOS arm64`) | `apac.amazon.nova-lite-v1:0` | `a76c160` | `results/final/C2/` |
| **C2_standin** | Rules & Shared Map (Offline) | FR-17 | **Local Simulation** (`mock_llm`) | Local server (`Linux x86_64`) | `rule-based-stand-in` | `071bbc6` | `results/final/C2_standin/` |
| **C3** | Memory & Habits | FR-19 | **Real Bedrock Execution** (`real_bedrock`) | Local server (`macOS arm64`) | `apac.amazon.nova-lite-v1:0` | `1c00f6f` | `results/final/C3/` |
| **C3_standin** | Memory & Habits (Offline) | FR-19 | **Local Simulation** (`mock_llm`) | Local server (`Linux x86_64`) | `rule-based-stand-in` | `071bbc6` | `results/final/C3_standin/` |
| **C4** | Rule Checker Under Attack | FR-15 | **Measured Verification** (`measured`) | In-process cloud (`Linux x86_64`) | Adversarial attacker | `071bbc6` | `results/final/C4/` |
| **C5** | Priority Scheduling & Inversion | FR-14, T8 | **Measured Verification** (`measured`) | In-process simulated clock | EDF scheduler | `071bbc6` | `results/final/C5/` |
| **C6** | Re-plan & Hand-over Latency | FR-16, T5 | **Real Bedrock Execution** (`real_bedrock`) | Local server (`macOS arm64`) | `apac.amazon.nova-lite-v1:0` | `485d898` | `results/final/C6/` |
| **C6_local** | Re-plan Latency (Offline) | FR-16, T5 | **Local Simulation** (`mock_llm`) | Local server (`Linux x86_64`) | `rule-based-stand-in` | `071bbc6` | `results/final/C6_local/` |
| **C7** | Cloud Model Outage Fallback | FR-18 | **Real Bedrock Execution** (`real_bedrock`) | Local server (`macOS arm64`) | `apac.amazon.nova-lite-v1:0` | `6c89d37` | `results/final/C7/` |
| **C7_local** | Model Outage Fallback (Offline) | FR-18 | **Local Simulation** (`mock_llm`) | Local server (`Linux x86_64`) | `rule-based-stand-in` | `071bbc6` | `results/final/C7_local/` |
| **C8** | Latency Under Parallel Load | NFR-1 | **Real Bedrock Execution** (`real_bedrock`) | Local server (`macOS arm64`) | `apac.amazon.nova-lite-v1:0` | `65892f6` | `results/final/C8/` |
| **C8_local** | Parallel Load (Offline) | NFR-1 | **Local Simulation** (`mock_llm`) | Local server (`Linux x86_64`) | `rule-based-stand-in` | `071bbc6` | `results/final/C8_local/` |
| **C9** | Cloud Model Calls Per Task | NFR-4 | **Real Bedrock Execution** (`real_bedrock`) | Local server (`macOS arm64`) | `apac.amazon.nova-lite-v1:0` | `0489b22` | `results/final/C9/` |
| **C9_standin** | Model Calls Per Task (Offline) | NFR-4 | **Local Simulation** (`mock_llm`) | Local server (`Linux x86_64`) | `rule-based-stand-in` | `071bbc6` | `results/final/C9_standin/` |

---

## 3. Detailed Experiment Audit Findings (N1–N10)

All N2 to N10 results were regenerated on the red-team fix branch (`5ea3e6a-dirty`). No N run called AWS or Bedrock.
Each `env.json` records the real commit, command, seeds and run times; its AWS fields are `null`.

### N1 — IISc Campus Field Traces
- **Status:** `Not run`.
- **Finding:** No continuous physical Wi-Fi trace collection on the IISc campus was done.
- **Remediation:** Claims of physical Raspberry Pi field measurements are withdrawn. The files in `traces/`
  (`iisc_basement.csv`, `iisc_corridor.csv`, `iisc_lift.csv`) are labelled "short synthetic example for local testing".

### N2 — Poisson Outage Model
- **Status:** `Fixed` (`modelled`).
- **Finding:** The traces hold one outage, too few to fit, so the model is fitted to a seeded synthetic sample. The KS
  test (p = 0.85) runs on exponential draws and only checks the fitting code. The Monte Carlo now samples durations from
  the AIC-best fit (Weibull) with scipy's own parameters: C1 predicted success 100.00% vs C2 60.71% at λ = 20/h.
  C1's value follows from the assumed 60 s survival threshold. The verdict is computed; the hard-coded headline
  (98.4% vs 61.8%) and the hard-coded "N3 measured" overlay points are removed.

### N3 — Network Degradation (analytical model; planned as trace replay)
- **Status:** `Fixed` (`modelled`).
- **Finding:** No trace is replayed and no Nimbus code runs: 720 rows come from closed-form formulas with seeded noise
  over six hand-set profiles. C1 recovery over the 120 outage rows has median 2.37 s, mean 2.33 s, p95 3.40 s, and C1
  success is 240/240; both are fixed by the formulas (recovery drawn from U(1.2, 3.5) s, success whenever the outage is
  under 60 s). The earlier 1.31 s mean averaged in rows with no outage. Measured recovery is in R7 and R9.

### N4 — Duplicate and Replayed Messages
- **Status:** `Fixed` (`simulated`).
- **Finding:** 5,000 synthetic messages over 10 seeds to a live in-process `server.py`: 0 steps executed twice,
  1,500/1,500 repeated message ids dropped (including 500 replays with an altered text), 1,500/1,500 repeat cancels of a
  cancelled task refused with 409, 1,000/1,000 fresh requests accepted; `GET /tasks` shows no task from an altered replay.
  The categories formerly called "stale lease version" and "shuffled order" were a repeat cancel and fresh requests;
  they are renamed. No real stale-version or re-ordering injection is run here, and the server writes no persistent
  drop log (each drop's reason is in its HTTP answer, recorded by the harness).

### N5 — Selective Sharing
- **Status:** `Fixed` (`simulated`).
- **Finding:** The per-seed RNG now draws 30 events (zone and type) and the live leases per seed: 300 events, 72 unique
  zone/type events, all 15 zones, 39 events in a zone that a lease from the other wing routes through. Recall 100%
  (441 TP, 0 FN), precision 100%. The expected set encodes the FR-11 rule from the pack's topology, so this checks the
  code against the rule, not the rule itself.

### N6 — Audit Replay & Determinism
- **Status:** `Fixed` (`simulated`).
- **Finding:** 10/10 seeded scenarios gave byte-identical decision logs in two processes with different
  `PYTHONHASHSEED` (147 rows, empty diff). The swimlane plot is now drawn from seed 7's real rows; the literal "100%
  timeline reconstruction" is removed.

### N7 — Security and Privacy Audit
- **Status:** `Fixed` (`static_audit`).
- **Finding:** 10/10 static checks pass, with the count and verdict computed from the checks. It scans this checkout
  only (declared IAM, tracked source, data manifest, WAN schemas), not git history, the deployed account or traffic.
  SEC-07 now uses `scripts/audit_data.py`'s PII patterns over every manifest-listed dataset. SEC-10 no longer
  string-matches `contracts/topics.md`; it checks that no `contracts/*.schema.json` declares an inline image or binary
  field. The payload schemas do not forbid extra keys, which the schema check cannot rule out.

### N8 — Fleet Scalability (cloud side)
- **Status:** `Fixed` (`mock_llm`).
- **Finding:** The metric is the cloud's own request-to-decision time with the stand-in model (not edge decision
  latency), under synthetic arrivals (not MIMIC-IV). Best of 3 interleaved runs per point after 5 warm-up runs:
  10 robots 1.10x and 15 robots 1.15x the 3-robot p95 on average, worst seed 1.44x, 10/10 seeds within 1.5x. Without
  the warm-up, seed 1 failed (its baseline was timed while the process still ran about twice as fast).

### N9 — Cost per Task
- **Status:** `Fixed` (`modelled`).
- **Finding:** Calls and tokens now come from C9's real-Bedrock records (no random draws): C1 1.18 vs C2 5.27 calls
  per task, 22.4% (95% CI 19.8% to 25.2%), so NFR-4 passes on measured counts. The dollars are modelled from Bedrock list
  prices and a Fargate share (0.5 vCPU, 1 GB per `main.tf`, hourly rates divided by 3600, about 7.5 s per task from C9's
  run rate): C1 \$0.000226, C2 \$0.000555, C3 \$0.000052 per task. The live CloudWatch / Cost Explorer calls, the stored
  billing records, the hard-coded account id and the hard-coded success points are removed.

### N10 — Operator Console Validation (cloud side)
- **Status:** `Fixed` (`measured`, cloud acknowledgement only).
- **Finding:** Run against a local in-process `server.py` on 127.0.0.1, not the deployed AWS cloud; with
  `NIMBUS_CLOUD_URL` set the runner exits non-zero if `GET /health` fails instead of falling back. Control-API round trip
  (`POST /tasks/{id}/control`): cancel p95 0.057 s, pause p95 0.055 s, max 0.062 s; 40/40 acknowledged with a new
  stop-lease version. SC-1 completed through the requester API with a simulated edge completion (the script posts
  `OUTPUT_READY`). Delivery of the stop lease to an edge or robot is not measured. The earlier "40 live operations on
  `ap-south-1`, p95 0.328 s" claim has no committed data and is withdrawn. The `.webm` videos predate this change.

---

## 4. Detailed Cloud Experiment Audit Findings (C1–C9)

### C1 — Plain-Language Request Understanding
- **Status:** `Verified` (`real_bedrock`).
- **Commits:** Result Commit `4c97ce3` (Execution Base in env.json: `485d898`).
- **Provenance:** 300 clinical requests from `data/hospital_sim6/requests_test.jsonl` parsed via Bedrock Nova-Lite (`apac.amazon.nova-lite-v1:0`). Field accuracy: 98.1% (95% CI: [97.0%, 98.9%]), clarification recall: 75.0%, precision: 98.4%.
- **Deployed Cloud Verification:** `C1_deployed` confirmed 94.0% field accuracy and 72.6% clarification recall over live AWS API Gateway and ECS Fargate (`results/final/C1_deployed/`, commit `071bbc6` / `81f0b93-dirty`).
- **Offline Stand-in:** `C1_standin` reproduces pipeline with deterministic rule-based stand-in (`results/final/C1_standin/`).

### C2 — Natural Language Rules & Shared Map Updates
- **Status:** `Verified` (`real_bedrock`).
- **Commits:** Result Commit `a76c160` (Execution Base in env.json: `485d898`).
- **Provenance:** Evaluated 10 natural language rules and 20 dynamic map updates. Nova Lite correctly interpreted 9/10 rules (1 complex phrasing edge-case honestly recorded as fail on strict 10/10 bar); all map updates reflected within 5 minutes (p95 = 1.60 s).

### C3 — Memory & Clinician Habit Disambiguation
- **Status:** `Verified` (`real_bedrock`).
- **Commits:** Result Commit `1c00f6f` (Execution Base in env.json: `485d898`).
- **Provenance:** 20 context-dependent requests tested with memory enabled vs disabled. 10/10 habit cases disambiguated without unnecessary follow-up questions; 0 habit overrides when explicit destination specified.

### C4 — Rule Checker Adversarial Defense
- **Status:** `Verified` (`measured`).
- **Commits:** Result Commit `071bbc6` (Execution Base in env.json: `81f0b93-dirty`).
- **Provenance:** 180 invalid lease proposals generated by adversary simulator (unknown cluster, wrong robot, cross-zone assignment, closed zone, unknown destination). 100% (180/180) vetoed with expected rule cited; 0/20 valid controls wrongly vetoed; rule-based fallback triggered after 2 failed model allocations.

### C5 — Priority Queue Scheduling & Inversion Prevention
- **Status:** `Verified` (`measured`).
- **Commits:** Result Commit `071bbc6` (Execution Base in env.json: `81f0b93-dirty`).
- **Provenance:** 113,518 tasks evaluated across 10 random seeds and 6 load levels on simulated hospital clock. Nimbus EDF scheduler exhibited exactly 0 priority inversions (compared to 25,009 inversions in FIFO baseline), maintaining 0.0 urgent task deadline miss ratio at load factor $\rho = 1.3$.

### C6 — Re-planning & Hand-over Latency
- **Status:** `Verified` (`real_bedrock`).
- **Commits:** Result Commit `485d898` (Execution Base in env.json: `9a80a4e`).
- **Provenance:** 32 unexpected edge events (corridor blockage, robot fault, handover request). Decision p95 = 1.58 s (p50 = 0.84 s, model latency p50 = 876 ms), well within 30-second requirement. 18/18 revised lease versions successfully avoided closed zones and failed robots.

### C7 — Cloud Model Outage Fallback
- **Status:** `Verified` (`real_bedrock`).
- **Commits:** Result Commit `6c89d37` (Execution Base in env.json: `65892f6`).
- **Provenance:** Injected 600-second Bedrock API outage mid-run. 14 requests arrived during outage: 5 leased via rule fallback, 9 queued, 0 model crashes, 100% issued with reduced-autonomy notice. 14/14 tasks leased prior to outage completed without disruption.

### C8 — Latency Under Parallel Load
- **Status:** `Verified` (`real_bedrock`).
- **Commits:** Result Commit `65892f6` (Execution Base in env.json: `0489b22`).
- **Provenance:** Evaluated under closed-loop concurrency (up to 64 parallel client workers) and open-loop Poisson traffic. Worst p95 latency = 2.13 s with 0 HTTP errors. Fitted queue capacity = ~44.9 requests/s.

### C9 — Cloud Model Calls per Task (C1 vs C2 vs C3)
- **Status:** `Verified` (`real_bedrock`).
- **Commits:** Result Commit `0489b22` (Execution Base in env.json: `4c97ce3-dirty`).
- **Provenance:** Measured model call consumption across T1–T5. Leased edge autonomy (C1) consumed 1.18 model calls/task compared to 5.27 calls/task in cloud-only relay (C2), achieving a call ratio of 22.4% (well under the 50.0% NFR-4 threshold).

