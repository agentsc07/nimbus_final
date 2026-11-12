# Nimbus P4 Experiment Package: Network and Infrastructure (N1 to N10)

**Where it ran:** a local Windows laptop. No N experiment called AWS or Bedrock, and none ran against the deployed cloud.
N4, N6, N8 and N10 run Nimbus code in-process on 127.0.0.1 with the rule-based stand-in model; N9 prices the call and
token counts that C9 measured with real Bedrock.

**Commit:** every run stamps its own `git rev-parse HEAD` (with `-dirty` when the tree had uncommitted changes), the
command and the seeds in its `env.json`. This set was produced at `5ea3e6a-dirty` (the red-team fix branch, uncommitted).

**Scope:** experiments N1 to N10. Every number below is computed by the runner from its own records; where a verdict
rests on a model's assumptions rather than a measurement, the row says so.

---

## 1. Results

| Run | PRD | Verdict | Measured | Source | PRD pass bar | Command | Evidence |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **N1** (real network traces) | E4 input | **Not run** | No campus traces were collected; the three files in `traces/` are labelled "short synthetic example for local testing" | `not_run` | Continuous campus trace collection; RTT/loss histograms | n/a | `traces/` |
| **N2** (Poisson outage model) | E4 | **PASS** (model) | C1 predicted success 100.00% vs C2 60.71% at λ = 20/h (10 seeds × 10,000 missions, Weibull durations by AIC); KS p = 0.85 on synthetic exponential inter-arrivals. C1's value follows from the assumed 60 s survival threshold. | `modelled` | KS-test p ≥ 0.05 on exponential inter-arrivals; C1 predicted success ≥ 90% | `python results/final/N2/run_n2.py` | `results/final/N2/` |
| **N3** (network degradation, analytical model; planned as trace replay) | FR-6, NFR-2 | **PASS** (model) | C1 recovery over the 120 outage rows: median 2.37 s, mean 2.33 s, p95 3.40 s; C1 success 240/240; C2 63.3%, C3 63.7%. Both C1 numbers are fixed by the formulas. | `modelled` | Normal operation resumed within 60 to 120 s (NFR-2); success ≥ 90% | `python results/final/N3/run_n3.py` | `results/final/N3/` |
| **N4** (duplicate and replayed messages at the cloud ingress) | FR-8 | **PASS** | 0 steps executed twice over 5,000 messages in 10 seeds; 1,500/1,500 repeated message ids dropped; 1,500/1,500 repeat cancels of a cancelled task refused with 409; 1,000/1,000 fresh requests accepted | `simulated` | Zero steps executed twice; every drop logged with reason | `python results/final/N4/run_n4.py` | `results/final/N4/` |
| **N5** (selective sharing) | FR-11 | **PASS** | Recall 100% (TP 441, FN 0), precision 100% over 300 seeded random events (72 unique zone/type events, 15/15 zones, 10 lease layouts) | `simulated` | Recall 100% (every affected cluster told); high precision | `python results/final/N5/run_n5.py` | `results/final/N5/` |
| **N6** (audit replay and determinism) | FR-20, NFR-6 | **PASS** | 10/10 seeds byte-identical across two processes with different `PYTHONHASHSEED`; 147 decision rows; `e6_seed_diff.txt` is 0 bytes | `simulated` | Every timeline replays; seeded reruns byte-identical | `python results/final/N6/run_n6.py` | `results/final/N6/` |
| **N7** (security and privacy audit) | NFR-5 | **PASS** | 10/10 static checks: 0 unjustified IAM wildcards, 0 secret-pattern hits, 0 manifest or PII problems, no inline image field in any WAN schema | `static_audit` | No wildcard IAM on data; no secrets in code; 100% synthetic data; images only inside OUTPUT_READY | `python results/final/N7/run_n7.py` | `results/final/N7/` |
| **N8** (scalability, cloud side) | NFR-3 | **PASS** | Cloud request-to-decision p95 (stand-in model, best of 3) vs 3 robots: 10 robots 1.10x, 15 robots 1.15x (means), worst seed 1.44x; 10/10 seeds within 1.5x | `mock_llm` | p95 decision latency at 10+ robots ≤ 1.5x the 3-robot baseline | `python results/final/N8/run_n8.py` | `results/final/N8/` |
| **N9** (cost per task) | NFR-4 | **PASS** | From C9's real-Bedrock records: C1 1.18 vs C2 5.27 calls per task, 22.4% (95% CI 19.8% to 25.2%); modelled cost per task C1 \$0.000226, C2 \$0.000555, C3 \$0.000052 | `modelled` | C1 model calls ≤ 50% of C2; cost per task reported for all configurations | `python results/final/N9/run_n9.py` | `results/final/N9/` |
| **N10** (requester app and operator console) | FR-21, FR-22 | **PASS (cloud side only)** | Local in-process server: control-API round trip p95 0.057 s (cancel), 0.055 s (pause), max 0.062 s; 40/40 acknowledged with a new stop-lease version; SC-1 completed with a simulated edge completion. Stop-lease delivery to an edge or robot not measured. | `measured` | SC-1 completes from app; cancel or override reaches robots within 5 s | `python results/final/N10/run_n10.py --no-video` | `results/final/N10/` |

The folder READMEs carry the full notes; [RESULTS.md](RESULTS.md) has the same rows with plots and commits.

---

## 2. Directory structure

Each folder has `run_n<n>.py`, `summary.csv` (with a `source` column), `plots/` (`.png` at 300 dpi and `.svg`),
`env.json` (commit with `-dirty` flag, command, seeds, run times, target, model; the AWS fields are `null`) and a
`README.md` in the [results guide](../../docs/RESULTS_GUIDE.md) format that `experiments/cloud/report.py` reads.

```
results/final/
├── SUMMARY.md                 # this file
├── N2/  outage_model.json     # synthetic sample, trace observations, fits, Monte Carlo results, verdict
├── N3/  raw/model_meta.json   # the formulas and hand-set profiles behind summary.csv (720 modelled rows)
├── N4/  e6_injection.csv      # one row per message: HTTP status, outcome, reason; state_check.json from GET /tasks
├── N5/  e6_sharing.csv        # one row per (event, cluster): expected vs informed
├── N6/  e6_replay.json        # per-seed decision counts and sha256; e6_seed_diff.txt (empty)
├── N7/  findings.json         # what each check found; audit_iam.txt, secret_scan_report.txt, manifest.json
├── N8/  e7.csv                # per (seed, fleet size): best-of-3 p50/p95, every run's p95, waits, misses; arrival_file.csv
├── N9/  cost.csv              # one row per C9 task: calls, tokens, priced terms; cost_formula_sheet.json
└── N10/ cancel.csv, sc1.json  # 40 timed control calls; SC-1 steps; the .webm videos predate this run (see its README)
```

---

## 3. Key findings and limits

1. **No field traces (N1, N2, N3).** N1 was not run. The `traces/` files are synthetic and hold one outage, so N2 fits
   its outage model to a seeded synthetic sample, and its KS test checks the fitting code, not a network. N3 is a set of
   closed-form formulas over six hand-set profiles; nothing is replayed. In both, C1's success follows from an assumed
   60 s survival threshold. Measured recovery and safe parking are in R7 and R9.
2. **Ingress de-duplication (N4) is measured on the real server code.** Repeated message ids, including replays with
   an altered text, were acknowledged and never executed again, and `GET /tasks` shows no task from an altered replay.
   N4 does not inject stale lease versions or re-ordered edge messages (R6 covers stale versions at the edge). The
   server answers each drop with a reason but writes no persistent drop log; the harness records each answer.
3. **Determinism (N6)** holds for the seeded orchestrator scenario with the offline model on a fixed clock.
4. **Selective sharing (N5)** matches the FR-11 rule on 300 random events, including leases that cross wings. It checks
   the code against the rule, not whether the rule informs the right people.
5. **Security (N7)** is a static scan of this checkout: declared IAM, tracked source, the data manifest and the WAN
   schemas. It does not cover git history, the deployed account or runtime traffic. The escalation payload schemas do
   not forbid extra keys, so the schemas alone do not exclude an inline image in, say, an UNEXPECTED_EVENT payload.
6. **Scaling (N8)** measures the cloud's own decision time with the stand-in model under synthetic arrivals (not
   MIMIC-IV), not edge decision latency. The worst seed is 1.44x against a 1.5x bar and single runs are noisy: without
   the warm-up runs the first seed failed at about 1.7x to 2.0x because its baseline was timed while the process still
   ran fast.
7. **Cost (N9)** uses C9's measured calls and tokens, so the NFR-4 ratio (22.4%) is measured. The dollars are modelled:
   Bedrock list prices plus a Fargate share of about 7.5 s of a 0.5 vCPU / 1 GB task per task, taken from C9's run rate.
   Other AWS terms are left out. No billing data or AWS API call is involved.
8. **Operator control (N10)** measures the cloud's acknowledgement of cancel and pause on a local server. Whether the
   stop lease reaches an edge and a robot within 5 s is not measured, and SC-1's completion is posted by the script.
   Earlier claims of 40 live operations on the deployed AWS cloud have no committed data and are withdrawn.
