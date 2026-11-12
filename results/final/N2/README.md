# N2: Poisson model of network breakdown

- **Claim:** A Poisson outage model (fitted to synthetic inputs) predicts that leased edge autonomy (C1) keeps mission success above 90% where a cloud relay (C2) does not.
- **PRD pass bar:** KS-test p >= 0.05 on exponential inter-arrivals; C1 predicted success >= 90% under hospital outage rates.
- **Measured:** model over synthetic inputs: C1 predicted success 100.00% (seeds range 100.00% to 100.00%) vs C2 60.71% at lambda=20/hr (10 seeds x 10000 missions, weibull durations by AIC); KS p=0.8527 on synthetic exponential inter-arrivals
- **Verdict:** PASS
- **Source of numbers:** modelled (Monte Carlo over synthetic inputs, no system run)
- **Command:** `python results/final/N2/run_n2.py`
- **Commit:** 5ea3e6aab3569b621b727457687dff63687cf70f-dirty, run 2026-11-12T08:24:25Z to 2026-11-12T08:24:28Z

## Plots

![duration_survival](plots/duration_survival.png)
![interarrival_hist](plots/interarrival_hist.png)
![qq_plot](plots/qq_plot.png)
![success_vs_lambda](plots/success_vs_lambda.png)

## Notes

- Inputs are synthetic. The traces in traces/ are labelled 'short synthetic example for local testing' and hold 1 outage(s) in 60 s, too few to fit; they are parsed and recorded in outage_model.json (trace_observations) but the fit uses a seeded synthetic sample (see inputs.generator).
- The KS test is run on inter-arrivals drawn from an exponential distribution, so a high p-value is expected by construction: it checks the fitting code, not a real network. No claim about real hospital outages follows from it.
- Success model (assumptions, not measurements): a mission of 90 s meets Poisson outages; C1 fails only if an outage lasts 60 s or more, C2 if one lasts 2 s or more. Durations are sampled from the AIC-best fit (weibull) with scipy's parameters.
- Under that fit P(outage >= 60 s) = 4.2e-13 and P(outage < 2 s) = 3.2e-03, so C1's success is fixed by the 60 s assumption and C2's is essentially P(no outage in 90 s) = exp(-lambda x T). The result restates the assumptions; it is not evidence that C1 survives real outages.
- Verdict rule: PASS iff KS p >= 0.05 and mean C1 success at lambda=20/hr >= 90%; both are computed above.
- An earlier version printed a hard-coded headline (98.4% vs 61.8%) and overlaid hard-coded 'N3 measured' points; both are removed. N3 is itself an analytical model, not a measurement.
