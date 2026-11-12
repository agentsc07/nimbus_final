# N6: Audit replay and determinism

- **Claim:** A seeded scenario's decision log is reproduced byte for byte when the scenario is re-run in another process.
- **PRD pass bar:** Every timeline replays (FR-20); seeded reruns are byte-identical (empty diff) (NFR-6).
- **Measured:** 10/10 seeds byte-identical between two processes (sha256 equal, 0 diff bytes in e6_seed_diff.txt); 147 decision rows in total (10 to 20 per seed), 13 lease issues
- **Verdict:** PASS
- **Source of numbers:** simulated (in-process orchestrator on a fixed clock via scripts/replay_check.scenario, two processes per seed, model offline stand-in)
- **Command:** `python results/final/N6/run_n6.py`
- **Commit:** 5ea3e6aab3569b621b727457687dff63687cf70f-dirty, run 2026-11-12T08:26:34Z to 2026-11-12T08:26:40Z

## Plots

![timeline_swimlane](plots/timeline_swimlane.png)

## Notes

- What is checked: re-running a seeded scenario (8 requests through the orchestrator with the offline model, fixed clock) in a separate process with a different PYTHONHASHSEED gives the same decision log, byte for byte.
- The decision rows compared are who/inputs/output/lease_version (scripts/replay_check.scenario); timestamps are not part of them. Replaying a log from a deployed run, or with the real Bedrock model, is not tested here.
- The swimlane is drawn from seed 7's actual rows (x = row order in the log). Earlier versions drew a hand-written event list and reported a literal '100% timeline reconstruction'; both are removed.
- Verdict rule: PASS iff every seed's two runs have equal sha256 and an empty diff.
