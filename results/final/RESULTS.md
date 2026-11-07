# Experiment results

Built by `python experiments/cloud/report.py` from each folder's README.md and env.json, never typed by hand. Every row links to a folder with the raw records, summary, plots and environment. How to add a row: [docs/RESULTS_GUIDE.md](../../docs/RESULTS_GUIDE.md). Rows marked *to be filled* have no result folder with a README yet.

Source: `real_bedrock` = Amazon Bedrock Nova Lite (deployed cloud or our own local server); `real_slm` = a real edge model; `mock_llm` = the rule-based stand-in model (protocol and code behaviour, not model quality); `measured` = no model involved, or a physical/simulated measurement; `modelled` / `simulated` = computed from a model or a simulation rather than the running system.

## Cloud (C1 to C9)

| Run | PRD | Verdict | Measured | Source | Plots | Commit |
| --- | --- | --- | --- | --- | --- | --- |
| [C1](C1/README.md) | FR-13 | PASS | bedrock: field accuracy 98.1% (95% CI 97.0% to 98.9%), clarification recall 75.0%, precision 98.4%, 300 request decisions | real_bedrock | [clarification_confusion](C1/plots/clarification_confusion.png), [decision_latency_cdf](C1/plots/decision_latency_cdf.png), [field_accuracy](C1/plots/field_accuracy.png) | 485d898 |
| [C1_deployed](C1_deployed/README.md) | FR-13 | PASS | bedrock: field accuracy 94.0% (95% CI 92.2% to 95.4%), clarification recall 72.6%, precision 92.4%, 300 request decisions | real_bedrock | [clarification_confusion](C1_deployed/plots/clarification_confusion.png), [decision_latency_cdf](C1_deployed/plots/decision_latency_cdf.png), [field_accuracy](C1_deployed/plots/field_accuracy.png) | 81f0b93-dirty |
| [C1_standin](C1_standin/README.md) | FR-13 | PASS | standin: field accuracy 98.6% (95% CI 96.5% to 99.5%), clarification recall 100.0%, precision 100.0%, 100 request decisions | mock_llm (standin) / measured (rules) | [clarification_confusion](C1_standin/plots/clarification_confusion.png), [field_accuracy](C1_standin/plots/field_accuracy.png) | cee7c04-dirty |
| [C2](C2/README.md) | FR-17 | FAIL | rules applied correctly 9/10 (apac.amazon.nova-lite-v1:0); effect on deliveries correct 7/7; map changes shown within 5 min 20/20 (p95 1.60 s); next request to the same place avoided the closed zone 20/20 | real_bedrock | [map_update_cdf](C2/plots/map_update_cdf.png), [rules_outcome](C2/plots/rules_outcome.png) | 485d898 |
| [C2_standin](C2_standin/README.md) | FR-17 | PASS | rules applied correctly 10/10 (rule-based-stand-in); effect on deliveries correct 7/7; map changes shown within 5 min 21/21 (p95 0.03 s); next request to the same place avoided the closed zone 21/21 | mock_llm | [map_update_cdf](C2_standin/plots/map_update_cdf.png), [rules_outcome](C2_standin/plots/rules_outcome.png) | 81f0b93-dirty |
| [C3](C3/README.md) | FR-19 | PASS | memory on: 19/20 cases right, habit cases resolved without asking 10/10; memory off: the same habit requests asked 10/10 times (questions saved by memory) | real_bedrock | [memory_ablation](C3/plots/memory_ablation.png) | 485d898 |
| [C3_standin](C3_standin/README.md) | FR-19 | PASS | memory on: 20/20 cases right, habit cases resolved without asking 10/10; memory off: the same habit requests asked 10/10 times (questions saved by memory) | mock_llm | [memory_ablation](C3_standin/plots/memory_ablation.png) | 81f0b93-dirty |
| [C4](C4/README.md) | FR-15 | PASS | part A: 0/180 invalid proposals approved (Wilson 95% upper bound 2.1%), 180/180 vetoed citing the expected rule, 0/20 valid controls wrongly vetoed; part B: 0 invalid leases from 60 adversarial requests, fallback used 54/54 times it was required, at most 2 model proposals per request | measured | [checker_funnel](C4/plots/checker_funnel.png), [end_to_end_outcomes](C4/plots/end_to_end_outcomes.png), [veto_by_kind](C4/plots/veto_by_kind.png) | 81f0b93-dirty |
| [C5](C5/README.md) | FR-14, T8 | PASS | queue inversions: ours 0, first-come-first-served 25009 over 113518 tasks (10 seeds x 3 fleet sizes x 6 loads x 2 h); at load 1.3 with 4 robots urgent miss ratio ours 0.0 vs fifo 0.774, routine 0.053 vs 0.023; T8: urgent served next = True | measured | [miss_ratio_vs_load](C5/plots/miss_ratio_vs_load.png), [robot_gantt](C5/plots/robot_gantt.png), [wait_cdf_by_priority](C5/plots/wait_cdf_by_priority.png) | 81f0b93-dirty |
| [C6](C6/README.md) | FR-16, T5 | PASS | decision p95 1.58 s, p50 0.84 s over 32 events; 18 new lease versions, 18/18 avoid the closed zone or failed robot; outcomes {'rerouted lease': 10, 'operator alerted (no route left)': 14, 'another robot took over': 8} | real_bedrock | [actions](C6/plots/actions.png), [decision_breakdown](C6/plots/decision_breakdown.png), [replan_latency_cdf](C6/plots/replan_latency_cdf.png) | 9a80a4e |
| [C6_local](C6_local/README.md) | FR-16, T5 | PASS | decision p95 0.02 s, p50 0.02 s over 32 events; 18 new lease versions, 18/18 avoid the closed zone or failed robot; outcomes {'rerouted lease': 10, 'operator alerted (no route left)': 14, 'another robot took over': 8} | mock_llm | [actions](C6_local/plots/actions.png), [decision_breakdown](C6_local/plots/decision_breakdown.png), [replan_latency_cdf](C6_local/plots/replan_latency_cdf.png) | 81f0b93-dirty |
| [C7](C7/README.md) | FR-18 | PASS | 14 requests during the 600 s outage: 5 leased, 9 queued for a robot, 0 answered by the model, 14 carried the reduced-autonomy notice; 14/14 tasks leased before the outage completed; breaker/fault seen at 300.21 s, normal again at 1560.37 s (outage 300 to 900 s) | real_bedrock | [outage_timeline](C7/plots/outage_timeline.png) | 65892f6 |
| [C7_local](C7_local/README.md) | FR-18 | PASS | 32 requests during the 600 s outage: 9 leased, 23 queued for a robot, 0 answered by the model, 32 carried the reduced-autonomy notice; 14/14 tasks leased before the outage completed; breaker/fault seen at 300.86 s, normal again at 916.99 s (outage 300 to 900 s) | mock_llm | [outage_timeline](C7_local/plots/outage_timeline.png) | 81f0b93-dirty |
| [C8](C8/README.md) | NFR-1 (cloud) | PASS | at 0.5 req/s: p95 0.932 s, errors 0.0; worst p95 over all levels 2.13 s; p95 first above 30 s at N=None; fitted S=0.24 s, c=11 -> capacity about 44.9 req/s | real_bedrock | [latency_vs_concurrency](C8/plots/latency_vs_concurrency.png), [open_loop_vs_mmc](C8/plots/open_loop_vs_mmc.png), [throughput](C8/plots/throughput.png) | 0489b22 |
| [C8_local](C8_local/README.md) | NFR-1 (cloud) | PASS | at 0.5 req/s: p95 0.042 s, errors 0.0; worst p95 over all levels 2.38 s; p95 first above 30 s at N=None; fitted S=0.02 s, c=2 -> capacity about 83.3 req/s | mock_llm | [latency_vs_concurrency](C8_local/plots/latency_vs_concurrency.png), [open_loop_vs_mmc](C8_local/plots/open_loop_vs_mmc.png), [throughput](C8_local/plots/throughput.png) | 81f0b93-dirty |
| [C9](C9/README.md) | NFR-4 | PASS | calls per task C1 1.18, C2 5.27, C3 0.00; C1/C2 = 22.4% | real_bedrock | [calls_per_task](C9/plots/calls_per_task.png) | 4c97ce3-dirty |
| [C9_standin](C9_standin/README.md) | NFR-4 | PASS | calls per task C1 1.16, C2 5.16, C3 0.00; C1/C2 = 22.4% | mock_llm | [calls_per_task](C9_standin/plots/calls_per_task.png) | cee7c04-dirty |

## Robot and edge (R1 to R10)

| Run | PRD | Verdict | Measured | Source | Plots | Commit |
| --- | --- | --- | --- | --- | --- | --- |
| R1 | FR-1 | | to be filled (results in progress: [R1/](R1/)) | | | |
| R2 | FR-2 | | to be filled | | | |
| R3 | FR-2, FR-5 | | to be filled | | | |
| [R4](R4/README.md) | E1, NFR-1, FR-3 | PASS | qwen2.5:0.5b: p95 warm 0.122 s, JSON 100.0%, allowed 100.0%, rule fallbacks 0; qwen2.5:1.5b: p95 warm 0.166 s, JSON 100.0%, allowed 100.0%, rule fallbacks 0; qwen2.5:3b: p95 warm 0.189 s, JSON 100.0%, allowed 100.0%, rule fallbacks 0 | measured | [p95_latency](R4/plots/p95_latency.png), [validity](R4/plots/validity.png) | run 2026-11-07T17:36:22. |
| R5 | FR-4 | | to be filled (results in progress: [R5/](R5/)) | | | |
| [R6](R6/README.md) | FR-5 | PASS | 60 injections: 0 unauthorized task executions; 60/60 attempted invalid task commands prevented before MockRobot execution. Expiry produced 20 authorised safe-parking commands. | measured | [authorization_timeline](R6/plots/authorization_timeline.png), [injection_outcomes](R6/plots/injection_outcomes.png) | 20d9655 |
| [R7](R7/README.md) | FR-6, FR-10 | PASS | 30/30 seeded trials passed: R7-A delivered the buffered WAN event and completed navigation in 20/20 link-cut trials; R7-B safely parked in `east_waiting_approach` in 10/10 expiry trials (1.477–2.335 s). There were 0 post-expiry task-motion events. | measured | none | 81d3b18-dirty |
| R8 | FR-7 | | to be filled | | | |
| [R9](R9/README.md) | FR-10, FR-12, NFR-2 | PASS | R9-A: 600.375 s outage, 0.135 s reconciliation, 0.138 s lease-operation recovery, and 1 exactly-once processing effect. R9-B: 600.008 s outage, 0.120 s reconciliation, 0.122 s lease-operation recovery, and 1 exactly-once processing effect. Both SQLite outboxes drained from 1 to 0 and reported 0 conflicting active leases. | measured | [recovery_time](R9/plots/recovery_time.png), [result_lifecycle](R9/plots/result_lifecycle.png) | 52730e6-dirty |
| [R10](R10/README.md) | FR-9 | PASS | 11 envelopes: 5/5 expected-valid in-limit envelopes passed; 5/5 malformed envelopes rejected; OUTPUT_READY uses a result_ref, so artifact bytes are not part of this envelope test. | measured | [message_sizes](R10/plots/message_sizes.png), [validation_by_type](R10/plots/validation_by_type.png) | 77adaa6-dirty |

## Network and infrastructure (N1 to N10)

| Run | PRD | Verdict | Measured | Source | Plots | Commit |
| --- | --- | --- | --- | --- | --- | --- |
| N1 | E4 input | | to be filled | | | |
| [N2](N2/README.md) | E4 | PASS | KS test p=0.8527 >= 0.05; C1 predicted success 98.4% vs C2 61.8% at lambda=20/hr (AIC best fit: weibull) | modelled | [duration_survival](N2/plots/duration_survival.png), [interarrival_hist](N2/plots/interarrival_hist.png), [qq_plot](N2/plots/qq_plot.png), [success_vs_lambda](N2/plots/success_vs_lambda.png) | a87763f |
| [N3](N3/README.md) | FR-6, NFR-2 | PASS | Recovery time p95=3.40 s <= 60 s pass bar; C1 success 100.0% >= 90% across 720 runs | modelled | [completion_vs_rtt](N3/plots/completion_vs_rtt.png), [recovery_time_box](N3/plots/recovery_time_box.png), [success_vs_loss](N3/plots/success_vs_loss.png), [wan_bytes_per_task](N3/plots/wan_bytes_per_task.png) | a87763f |
| [N4](N4/README.md) | FR-8 | PASS | 0 duplicate steps executed across 500 injected messages in 10 seeded runs (100.0% deduplication) | simulated | [injection_outcomes](N4/plots/injection_outcomes.png), [timeline_dedup](N4/plots/timeline_dedup.png) | a87763f |
| [N5](N5/README.md) | FR-11 | PASS | Recall = 100.0% (FN=0, 100% pass bar met); Precision = 100.0% across 300 evaluations | simulated | [confusion_matrix](N5/plots/confusion_matrix.png), [precision_recall](N5/plots/precision_recall.png) | a87763f |
| [N6](N6/README.md) | FR-20, NFR-6 | PASS | 10/10 seeded replays byte-identical (0 diff bytes in e6_seed_diff.txt); 100% timeline reconstruction | simulated | [timeline_swimlane](N6/plots/timeline_swimlane.png) | a87763f |
| [N7](N7/README.md) | NFR-5 | PASS | 10/10 audit checks passed (0 unjustified IAM wildcards, 0 secrets, 100% synthetic datasets, 0 camera WAN leaks) | measured_real_system | [security_checklist](N7/plots/security_checklist.png) | a87763f |
| [N8](N8/README.md) | NFR-3 | PASS | 10-robot latency ratio = 1.13x <= 1.50x; 15-robot latency ratio = 1.10x <= 1.50x (10/10 seeds passed) | modelled | [arrival_rate](N8/plots/arrival_rate.png), [p95_latency_scale](N8/plots/p95_latency_scale.png), [waiting_miss_ratio](N8/plots/waiting_miss_ratio.png) | a87763f |
| [N9](N9/README.md) | NFR-4 | PASS | C1 calls = 1.69 vs C2 = 6.93 (24.4% <= 50.0% pass bar); C1 cost=$0.000544/task | measured | [cost_per_task_stacked](N9/plots/cost_per_task_stacked.png), [success_vs_cost](N9/plots/success_vs_cost.png) | a87763f |
| [N10](N10/README.md) | FR-21, FR-22 | PASS | Cancel p95=0.037s <= 5.0s, Override p95=0.037s <= 5.0s, max=0.043s; SC-1 verified | measured | [cancel_latency_cdf](N10/plots/cancel_latency_cdf.png) | a87763f |

## Scenario tests (T1 to T8, experiment E3)

| Run | PRD | Verdict | Measured | Source | Plots | Commit |
| --- | --- | --- | --- | --- | --- | --- |
| T1 | E3 | | to be filled | | | |
| T2 | E3 | | to be filled (results in progress: [T2/](T2/)) | | | |
| T3 | E3 | | to be filled | | | |
| [T4](T4/README.md) | E3 | per configuration (see Measured and the results table below) | C1: profile severe, outcome delivered, time-to-outcome (s) 8.398, obstacle decision latency (ms) 15.1, decided by SLM, deadline met; C2: profile severe, outcome STALLED -> escalated (relay could not resolve over the bad link), time-to-outcome (s) 5.22, obstacle decision latency (ms) 1711.1, decided by C2_RELAY, deadline FAIL; C3: profile severe, outcome delivered, time-to-outcome (s) 12.039, obstacle decision latency (ms) 1.5, decided by C3_FSM, deadline met | measured | [completion_time](T4/plots/completion_time.png), [decision_latency](T4/plots/decision_latency.png) | 81d3b18 |
| [T5](T5/README.md) | E3 | per configuration (see Measured and the results table below) | C1: cloud deployed, outcome NOT delivered (queued), cross-wing yes, wing sequence -, decided by None, llm 1, completion (s) None, deadline FAIL; C2: cloud deployed, outcome NOT delivered (queued), cross-wing yes, wing sequence -, decided by None, llm 2, completion (s) None, deadline FAIL; C3: cloud local, outcome None, cross-wing no, wing sequence -, decided by None, llm None, completion (s) None, deadline FAIL | measured | [handover](T5/plots/handover.png) | a32c832 |
| T6 | E3 | | to be filled (results in progress: [../../T6_results/](../../T6_results/)) | | | |
| [T7](T7/README.md) | E3 | per configuration (see Measured and the results table below) | C1: cloud deployed, places 3, report kind edge_filtered_digest, WAN bytes 148, bytes/place 49.3, survey status completed; C2: cloud deployed, places 3, report kind raw_observations, WAN bytes 12791, bytes/place 4263.7, survey status completed; C3: cloud local, places 3, report kind structured_counts, WAN bytes 322, bytes/place 107.3, survey status completed | measured | [wan_bytes](T7/plots/wan_bytes.png) | a32c832 |
| T8 | E3 | | to be filled (results in progress: [../../T8_results/](../../T8_results/)) | | | |

## Pass bars

| Run | PRD pass bar |
| --- | --- |
| C1 | >= 85% of details right on clear requests; most vague requests get a question (FR-13). |
| C1_deployed | >= 85% of details right on clear requests; most vague requests get a question (FR-13). |
| C1_standin | >= 85% of details right on clear requests; most vague requests get a question (FR-13). |
| C2 | Scripted changes reflected in the map within about 5 min in >= 80% of cases; 10 test rules applied correctly (FR-17). |
| C2_standin | Scripted changes reflected in the map within about 5 min in >= 80% of cases; 10 test rules applied correctly (FR-17). |
| C3 | Most of 20 context-dependent requests resolved without asking (FR-19). |
| C3_standin | Most of 20 context-dependent requests resolved without asking (FR-19). |
| C4 | No invalid lease issued; fallback after 2 failed proposals (FR-15). |
| C5 | An urgent task never waits behind a routine one in the queue (FR-14); T8 handled. |
| C6 | New plan issued within about 30 s on a good network (FR-16). |
| C6_local | New plan issued within about 30 s on a good network (FR-16). |
| C7 | Model calls forced to fail for 10 min mid-run: leased tasks continue; new requests still leased via the fallback; user told (FR-18). |
| C7_local | Model calls forced to fail for 10 min mid-run: leased tasks continue; new requests still leased via the fallback; user told (FR-18). |
| C8 | Request to lease p95 <= 30 s on a good network (NFR-1). |
| C8_local | Request to lease p95 <= 30 s on a good network (NFR-1). |
| C9 | C1 cloud LLM calls per task <= 50% of C2 (NFR-4). |
| C9_standin | C1 cloud LLM calls per task <= 50% of C2 (NFR-4). |
| R4 | Edge decisions complete within 10 s (p95) on the pinned edge hardware (NFR-1; FR-3). |
| R6 | Zero lease violations across 20 forbidden-zone, 20 expired-lease, and 20 outdated-version injections (FR-5). |
| R7 | No unsafe park, no post-expiry task motion, buffered WAN events delivered. |
| R9 | For each 600 s fault: one generated result retained/uploaded once; reconciliation <60 s; normal lease operation <120 s; no conflict. |
| R10 | 100% valid tested escalations; lease, check-in and escalation envelopes <= 2 KB; OUTPUT_READY artifacts 200 KB to 2 MB. |
| N2 | KS-test p >= 0.05 on exponential inter-arrivals; C1 predicted success >= 90% under hospital outage rates. |
| N3 | Normal operation resumed within 60-120 s (NFR-2); Success >= 90%. |
| N4 | Zero steps executed twice (FR-8); every drop logged with reason. |
| N5 | Recall 100% (every affected cluster told) (FR-11); high precision (few unaffected). |
| N6 | Every timeline replays (FR-20); seeded reruns are byte-identical (empty diff) (NFR-6). |
| N7 | No wildcard IAM on data; no secrets in code; 100% synthetic data; images only inside OUTPUT_READY (NFR-5). |
| N8 | p95 edge decision latency at 10+ robots <= 1.5x the 3-robot baseline (NFR-3). |
| N9 | C1 model calls <= 50% of C2 (NFR-4); Cost per task reported for all configurations. |
| N10 | SC-1 completes from app; cancel or override reaches robots within 5 s (FR-21, FR-22). |
| T4 | C1 fastest; C2 stalls on a bad link (PRD Table 3) |
| T5 | C1 > C2 >> C3 (PRD Table 3) |
| T7 | C1 least WAN bandwidth (edge filters) (PRD Table 3) |
