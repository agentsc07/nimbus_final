# N8: Scalability (cloud side)

- **Claim:** The cloud's request-to-decision time at 10 and 15 robots stays within 1.5x of the 3-robot baseline.
- **PRD pass bar:** p95 edge decision latency at 10+ robots <= 1.5x the 3-robot baseline (NFR-3).
- **Measured:** cloud request-to-decision p95 (stand-in model, best of 3 runs) vs 3 robots: 10 robots mean 1.10x, 15 robots mean 1.15x, worst seed 1.44x; 10/10 seeds within 1.50x at both sizes
- **Verdict:** PASS
- **Source of numbers:** mock_llm (in-process orchestrator via scripts/run_e7.simulate, scale pack with 3 clusters, synthetic arrivals, model offline stand-in)
- **Command:** `python results/final/N8/run_n8.py`
- **Commit:** 5ea3e6aab3569b621b727457687dff63687cf70f-dirty, run 2026-11-12T08:27:05Z to 2026-11-12T08:28:55Z

## Plots

![arrival_rate](plots/arrival_rate.png)
![p95_latency_scale](plots/p95_latency_scale.png)
![waiting_miss_ratio](plots/waiting_miss_ratio.png)

## Notes

- Metric: the cloud orchestrator's own wall time per request (orch.handle_request) with the offline stand-in model, measured in-process. It is not the edge decision latency that NFR-3 names, and it contains no model latency; the edge side of NFR-3 is not measured here.
- Arrivals are synthetic (scripts/run_e7.arrivals, one simulated hour per seed), not MIMIC-IV. Robot travel, queue waits and deadline misses are modelled from the scale pack's map, not measured.
- Timing: each (seed, fleet size) runs 3 times, interleaved across fleet sizes, and keeps the lowest p50 and p95 (decision_ms_p95_runs in e7.csv lists all runs); with about 40 to 60 requests per hour the p95 rests on the top 2 or 3 values, so single runs are noisy.
- Warm-up: 5 untimed 3-robot simulations run first (their p95s are in env.json). On the test laptop the first two to four simulations in a process ran about twice as fast as all later ones; without the warm-up seed 1's 3-robot baseline fell in the fast phase and seed 1 failed at 1.7x to 2.0x, an artefact of measurement order rather than of fleet size.
- Verdict rule: PASS iff in every seed the 10-robot and 15-robot p95 are both <= 1.50x the same seed's 3-robot p95.
