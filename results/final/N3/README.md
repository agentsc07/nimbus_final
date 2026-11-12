# N3: Network degradation (analytical model; planned as trace replay)

- **Claim:** Under an analytical model of six network profiles, leased edge autonomy (C1) recovers from outages within NFR-2's minute and keeps success >= 90%, unlike C2 and C3.
- **PRD pass bar:** Normal operation resumed within 60-120 s (NFR-2); Success >= 90%.
- **Measured:** analytical model, not a measurement: C1 recovery over 120 outage rows (Basement, N2-Synth-Mild, N2-Synth-Severe) median 2.37 s, mean 2.33 s, p95 3.40 s (<= 60 s); C1 success 240/240 (100.0%) vs C2 63.3%, C3 63.7%; both C1 numbers are fixed by the model's formulas
- **Verdict:** PASS
- **Source of numbers:** modelled (closed-form model with seeded noise, no system run)
- **Command:** `python results/final/N3/run_n3.py`
- **Commit:** 5ea3e6aab3569b621b727457687dff63687cf70f-dirty, run 2026-11-12T08:24:30Z to 2026-11-12T08:24:31Z

## Plots

![completion_vs_rtt](plots/completion_vs_rtt.png)
![recovery_time_box](plots/recovery_time_box.png)
![success_vs_loss](plots/success_vs_loss.png)
![wan_bytes_per_task](plots/wan_bytes_per_task.png)

## Notes

- This is not trace replay: no trace file is opened and no Nimbus code runs. Every row is computed from closed-form formulas with seeded noise over six hand-set profiles (see raw/model_meta.json). The four profiles named after traces are hand-set constants, not read from traces/.
- The C1 results hold by construction: C1 recovery is drawn from U(1.2, 3.5) s whenever the profile has an outage (so its p95 cannot exceed 3.5 s), and C1 counts as a success whenever the outage is under 60 s, which every profile is (longest 35 s). The PASS restates these assumptions; it is not evidence for FR-6 or NFR-2.
- Recovery statistics are over outage rows only (C1: 120 rows, C2: 120 rows); earlier versions averaged in rows with no outage.
- Verdict rule: PASS iff C1 recovery p95 over outage rows <= 60 s and C1 success >= 90%. For measured recovery and safe parking see R7 and R9.
- WAN bytes per task are hand-set baselines times seeded noise, not measured traffic.
