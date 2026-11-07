# N8: Scalability

- **Claim:** Fleet scaling across 3 to 15 robots demonstrates p95 decision latency strictly within 1.5x baseline.
- **PRD pass bar:** p95 edge decision latency at 10+ robots <= 1.5x the 3-robot baseline (NFR-3).
- **Measured:** 10-robot latency ratio = 1.13x <= 1.50x; 15-robot latency ratio = 1.10x <= 1.50x (10/10 seeds passed)
- **Verdict:** PASS
- **Source of numbers:** modelled
- **Command:** `python results/final/N8/run_n8.py`
- **Commit:** a87763fa837e38648a1c83ed5ae3b15fc28f5456

## Plots

![arrival_rate](plots/arrival_rate.png)
![p95_latency_scale](plots/p95_latency_scale.png)
![waiting_miss_ratio](plots/waiting_miss_ratio.png)
