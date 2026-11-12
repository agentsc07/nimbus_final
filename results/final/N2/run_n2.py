"""N2: Poisson model of network breakdown (an analytical model over SYNTHETIC inputs).

    python results/final/N2/run_n2.py

The three files in traces/ are labelled "short synthetic example for local testing" and together hold a single
outage (basement, about 20 s), too few to fit anything. This runner parses them and records what they contain, then
fits the outage model to a seeded synthetic sample (exponential inter-arrivals, mean 180 s; 10 hand-set durations plus
40 lognormal draws). The KS test therefore checks the fitting code on data drawn from an exponential, not a real
network. The Monte Carlo samples outage durations from the AIC-best fit with scipy's own parameterisation.
"""

import os
import json
import numpy as np
import scipy.stats as stats
import pandas as pd
import matplotlib.pyplot as plt
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))
sys.path.insert(0, os.getcwd())
from scripts.p4_shared import (
    COLOR_C1, COLOR_C2, COLOR_C3, COLOR_PASS_BAR,
    setup_matplotlib_style, save_plots, write_env_json, write_readme
)

TRACE_MIN_OUTAGES_TO_FIT = 10   # below this many trace outages the fit uses the synthetic sample (and says so)

def run_n2():
    out_dir = os.path.join("results", "final", "N2")
    plot_dir = os.path.join(out_dir, "plots")
    os.makedirs(plot_dir, exist_ok=True)
    setup_matplotlib_style()

    # 1. Parse traces
    traces = {
        "corridor": "traces/iisc_corridor.csv",
        "lift": "traces/iisc_lift.csv",
        "basement": "traces/iisc_basement.csv"
    }
    
    total_trace_duration = 0.0
    outage_durations = []
    good_durations = []
    trace_files = []

    for name, path in traces.items():
        if os.path.exists(path):
            df = pd.read_csv(path, comment="#")
            with open(path, encoding="utf-8") as fh:
                trace_files.append({"name": name, "path": path, "label": fh.readline().lstrip("# ").strip(),
                                    "samples": int(len(df)), "duration_s": float(df["time_sec"].max())})
            total_trace_duration += df["time_sec"].max()
            in_outage = False
            start_t = 0.0
            last_t = 0.0
            for _, row in df.iterrows():
                t = row["time_sec"]
                loss = row["loss_pct"]
                if loss >= 90.0:
                    if not in_outage:
                        in_outage = True
                        start_t = t
                        if t > last_t:
                            good_durations.append(t - last_t)
                else:
                    if in_outage:
                        in_outage = False
                        outage_durations.append(t - start_t)
                        last_t = t
            if in_outage:
                outage_durations.append(df["time_sec"].max() - start_t)

    trace_fit_feasible = len(outage_durations) >= TRACE_MIN_OUTAGES_TO_FIT
    # The traces hold too few outages to fit (see trace_observations in outage_model.json), so the model is fitted
    # to a seeded SYNTHETIC sample: 10 hand-set durations around the basement trace's ~20 s outage, 40 lognormal
    # durations and 50 exponential inter-arrivals (mean 180 s, i.e. about 20 outages per hour).
    np.random.seed(42)
    base_outages = np.array([19.0, 14.5, 22.0, 12.0, 18.5, 25.0, 8.5, 16.0, 21.5, 15.0])
    inter_arrivals = np.random.exponential(scale=180.0, size=50) # mean 180s between dead zones
    durations = np.concatenate([base_outages, np.random.lognormal(mean=2.6, sigma=0.5, size=40)])

    # Fit Poisson rate lambda (outages per second / hour)
    mean_ia = np.mean(inter_arrivals)
    lam = 1.0 / mean_ia # outages per second
    lam_hourly = lam * 3600.0 # ~20 outages per hour

    # KS test for exponential inter-arrival
    ks_res = stats.kstest(inter_arrivals, "expon", args=(0, mean_ia))

    # Duration fits: Exponential, Lognormal, Weibull
    # Exponential
    exp_params = stats.expon.fit(durations, floc=0)
    ll_exp = np.sum(stats.expon.logpdf(durations, *exp_params))
    aic_exp = 2 * 1 - 2 * ll_exp

    # Lognormal
    ln_params = stats.lognorm.fit(durations, floc=0)
    ll_ln = np.sum(stats.lognorm.logpdf(durations, *ln_params))
    aic_ln = 2 * 2 - 2 * ll_ln

    # Weibull
    wb_params = stats.weibull_min.fit(durations, floc=0)
    ll_wb = np.sum(stats.weibull_min.logpdf(durations, *wb_params))
    aic_wb = 2 * 2 - 2 * ll_wb

    aic_dict = {
        "exponential": {"aic": float(aic_exp), "params": [float(p) for p in exp_params]},
        "lognormal": {"aic": float(aic_ln), "params": [float(p) for p in ln_params]},
        "weibull": {"aic": float(aic_wb), "params": [float(p) for p in wb_params]}
    }
    best_dist = min(aic_dict.keys(), key=lambda k: aic_dict[k]["aic"])

    # Gilbert-Elliott parameters
    # Good state: avg good period = mean_ia
    # Bad state: avg bad period = mean(durations)
    mean_dur = np.mean(durations)
    p_GB = 1.0 / mean_ia
    p_BG = 1.0 / mean_dur
    loss_G = 0.005 # 0.5% loss in good
    loss_B = 0.995 # 99.5% loss in bad

    # Monte Carlo: sample outage durations from the AIC-best distribution with scipy's own (shape, loc, scale)
    # parameters (the earlier version fed lognorm's (s, loc, scale) into numpy's lognormal(mean, sigma)).
    best_rv = {"exponential": stats.expon, "lognormal": stats.lognorm, "weibull": stats.weibull_min}[best_dist]
    best_params = aic_dict[best_dist]["params"]
    C2_SURVIVES_BELOW_S = 2.0    # model assumption: the cloud relay survives only sub-2 s glitches
    C1_SURVIVES_BELOW_S = 60.0   # model assumption: leased autonomy rides out outages shorter than ~60 s

    # Monte Carlo 10,000 synthetic missions per seed (seeds 1 to 10)
    # We test multiple lambda scales: [2.0, 5.0, 10.0, 15.0, 20.0, 30.0] outages/hour
    test_lambdas = [2.0, 5.0, 10.0, 15.0, 20.0, 30.0]
    mission_duration_s = 90.0 # 1.5 min standard delivery task
    N_MISSIONS = 10000

    summary_rows = []
    mc_results = { "C1": {}, "C2": {} }

    for l_h in test_lambdas:
        mc_results["C1"][l_h] = []
        mc_results["C2"][l_h] = []

    for seed in range(1, 11):
        rng = np.random.default_rng(seed)
        for l_h in test_lambdas:
            curr_lam = l_h / 3600.0 # per second
            # Generate number of outages per mission ~ Poisson(curr_lam * T)
            k_outages = rng.poisson(curr_lam * mission_duration_s, size=N_MISSIONS)

            # C2 (Cloud Relay): fails if any non-reflex step encounters an outage during cloud call
            # Cloud calls happen every 6s on average (~15 calls per task).
            # If an outage occurs during a cloud call and exceeds 10s timeout, mission fails.
            # Sample outage durations for missions with >= 1 outage
            n_out = int(np.sum(k_outages))
            outage_lens = best_rv.rvs(*best_params, size=n_out, random_state=rng) if n_out > 0 else np.array([])
            
            # C2 success: no outages, or outages are very brief (< 2s)
            c2_successes = 0
            idx = 0
            for k in k_outages:
                if k == 0:
                    c2_successes += 1
                else:
                    lens = outage_lens[idx:idx+k]
                    idx += k
                    if np.max(lens) < C2_SURVIVES_BELOW_S: # survives only sub-2s glitches
                        c2_successes += 1
            
            c2_rate = c2_successes / N_MISSIONS

            # C1 (Leased Edge Autonomy): local execution inside lease;
            # Only fails if outage duration exceeds the lease expiry + max retry buffer (~60s)
            c1_successes = 0
            idx = 0
            for k in k_outages:
                if k == 0:
                    c1_successes += 1
                else:
                    lens = outage_lens[idx:idx+k]
                    idx += k
                    if np.max(lens) < C1_SURVIVES_BELOW_S: # survives outages up to 60s without failing
                        c1_successes += 1
            c1_rate = c1_successes / N_MISSIONS

            mc_results["C1"][l_h].append(c1_rate)
            mc_results["C2"][l_h].append(c2_rate)

            missions_with_outage = int(np.sum(k_outages > 0))
            summary_rows.append({
                "seed": seed,
                "lambda_hourly": l_h,
                "config": "C1",
                "missions": N_MISSIONS,
                "missions_with_outage": missions_with_outage,
                "successes": c1_successes,
                "success_rate": c1_rate,
                "duration_model": best_dist,
                "source": "modelled"
            })
            summary_rows.append({
                "seed": seed,
                "lambda_hourly": l_h,
                "config": "C2",
                "missions": N_MISSIONS,
                "missions_with_outage": missions_with_outage,
                "successes": c2_successes,
                "success_rate": c2_rate,
                "duration_model": best_dist,
                "source": "modelled"
            })

    # Save summary.csv
    df_summary = pd.DataFrame(summary_rows)
    summary_path = os.path.join(out_dir, "summary.csv")
    df_summary.to_csv(summary_path, index=False)

    c1_at_20 = float(np.mean(mc_results["C1"][20.0]))
    c2_at_20 = float(np.mean(mc_results["C2"][20.0]))
    c1_at_20_range = (float(np.min(mc_results["C1"][20.0])), float(np.max(mc_results["C1"][20.0])))
    ks_ok = bool(ks_res.pvalue >= 0.05)
    c1_ok = bool(c1_at_20 >= 0.90)
    verdict_pass = ks_ok and c1_ok

    # Save outage_model.json
    model_json = {
        "inputs": {
            "kind": "synthetic",
            "why": (f"traces/ holds {len(outage_durations)} outage(s) with loss >= 90% "
                    f"(fewer than {TRACE_MIN_OUTAGES_TO_FIT}), so the fit uses a seeded synthetic sample"),
            "generator": {"seed": 42, "inter_arrivals": "50 x exponential(scale=180 s)",
                          "durations": "10 hand-set values + 40 x lognormal(mean=2.6, sigma=0.5)"},
        },
        "trace_observations": {
            "files": trace_files,
            "total_duration_s": float(total_trace_duration),
            "outage_durations_s": [float(x) for x in outage_durations],
            "good_intervals_s": [float(x) for x in good_durations],
            "fit_feasible": trace_fit_feasible,
        },
        "poisson_arrival": {
            "mean_inter_arrival_sec": float(mean_ia),
            "lambda_per_sec": float(lam),
            "lambda_per_hour": float(lam_hourly),
            "ks_test_p_value": float(ks_res.pvalue),
            "ks_statistic": float(ks_res.statistic)
        },
        "duration_distribution": {
            "selected_best_fit": best_dist,
            "fits": aic_dict
        },
        "gilbert_elliott_markov_chain": {
            "p_GB": float(p_GB),
            "p_BG": float(p_BG),
            "loss_good_state": float(loss_G),
            "loss_bad_state": float(loss_B)
        },
        "monte_carlo": {
            "missions_per_seed": N_MISSIONS,
            "seeds": list(range(1, 11)),
            "mission_duration_s": mission_duration_s,
            "duration_distribution_sampled": best_dist,
            "assumptions": {"c1_survives_outages_shorter_than_s": C1_SURVIVES_BELOW_S,
                            "c2_survives_outages_shorter_than_s": C2_SURVIVES_BELOW_S},
            "c1_mean_success_at_20_outages_hr": c1_at_20,
            "c1_success_range_over_seeds_at_20_outages_hr": list(c1_at_20_range),
            "c2_mean_success_at_20_outages_hr": c2_at_20,
            "mean_success_by_lambda": {cfg: {str(l): float(np.mean(mc_results[cfg][l])) for l in test_lambdas}
                                       for cfg in ("C1", "C2")}
        },
        "verdict": {"ks_p_at_least_0_05": ks_ok, "c1_success_at_20_per_hr_at_least_0_90": c1_ok,
                    "result": "PASS" if verdict_pass else "FAIL"}
    }
    with open(os.path.join(out_dir, "outage_model.json"), "w", encoding="utf-8") as f:
        json.dump(model_json, f, indent=2)

    # --- PLOTS ---
    # Plot 1: Inter-arrival histogram with fitted exponential
    fig, ax = plt.subplots(figsize=(6.5, 4.5))
    count, bins, _ = ax.hist(inter_arrivals, bins=15, density=True, alpha=0.6, color=COLOR_C1, edgecolor="black", label="Synthetic inter-arrivals (seed 42)")
    x_grid = np.linspace(0, max(inter_arrivals), 200)
    pdf_exp = stats.expon.pdf(x_grid, 0, mean_ia)
    ax.plot(x_grid, pdf_exp, "r-", lw=2, label=f"Poisson Arrival Fit (λ={lam_hourly:.1f}/hr, p={ks_res.pvalue:.3f})")
    ax.set_title("N2: Outage inter-arrival times (synthetic) & Poisson fit")
    ax.set_xlabel("Inter-arrival Time (seconds)")
    ax.set_ylabel("Probability Density")
    ax.legend(loc="upper right")
    ax.grid(True)
    save_plots(fig, plot_dir, "interarrival_hist")

    # Plot 2: Q-Q Plot
    fig, ax = plt.subplots(figsize=(5.5, 5.0))
    res = stats.probplot(inter_arrivals, dist="expon", sparams=(0, mean_ia), plot=ax)
    ax.get_lines()[0].set_color(COLOR_C1)
    ax.get_lines()[0].set_markersize(5.0)
    ax.get_lines()[1].set_color(COLOR_PASS_BAR)
    ax.get_lines()[1].set_linewidth(1.8)
    ax.set_title("N2: Exponential Q-Q Plot (Outage Arrivals)")
    ax.set_xlabel("Theoretical Exponential Quantiles (seconds)")
    ax.set_ylabel("Sample quantiles, synthetic (seconds)")
    ax.grid(True)
    save_plots(fig, plot_dir, "qq_plot")

    # Plot 3: Duration survival curve
    fig, ax = plt.subplots(figsize=(6.5, 4.5))
    sorted_durs = np.sort(durations)
    survival_emp = 1.0 - np.arange(1, len(sorted_durs)+1) / len(sorted_durs)
    ax.step(sorted_durs, survival_emp, where="post", color="#111111", lw=2, label="Synthetic sample survival P(D > t)")

    t_grid = np.linspace(1, max(durations), 200)
    surv_exp = 1.0 - stats.expon.cdf(t_grid, *exp_params)
    surv_ln = 1.0 - stats.lognorm.cdf(t_grid, *ln_params)
    surv_wb = 1.0 - stats.weibull_min.cdf(t_grid, *wb_params)

    sel = lambda k: " [Selected]" if k == best_dist else ""
    ax.plot(t_grid, surv_exp, "--", color=COLOR_C3, label=f"Exponential (AIC={aic_exp:.1f}){sel('exponential')}")
    ax.plot(t_grid, surv_ln, "-", color=COLOR_C2, lw=2, label=f"Lognormal (AIC={aic_ln:.1f}){sel('lognormal')}")
    ax.plot(t_grid, surv_wb, ":", color=COLOR_C1, lw=2, label=f"Weibull (AIC={aic_wb:.1f}){sel('weibull')}")

    ax.set_title("N2: Outage Duration Survival Function P(Duration > t)")
    ax.set_xlabel("Duration (seconds)")
    ax.set_ylabel("Survival Probability")
    ax.set_ylim(-0.02, 1.05)
    ax.legend(loc="upper right")
    ax.grid(True)
    save_plots(fig, plot_dir, "duration_survival")

    # Plot 4: Predicted Success vs Lambda for C1 and C2
    fig, ax = plt.subplots(figsize=(7.0, 4.5))
    c1_means = [np.mean(mc_results["C1"][l]) for l in test_lambdas]
    c1_stds = [np.std(mc_results["C1"][l]) for l in test_lambdas]
    c2_means = [np.mean(mc_results["C2"][l]) for l in test_lambdas]
    c2_stds = [np.std(mc_results["C2"][l]) for l in test_lambdas]

    ax.plot(test_lambdas, c1_means, "o-", color=COLOR_C1, lw=2.2, label="C1: Nimbus Leased Autonomy (Modelled)")
    ax.fill_between(test_lambdas, np.array(c1_means) - 1.96*np.array(c1_stds), np.array(c1_means) + 1.96*np.array(c1_stds), color=COLOR_C1, alpha=0.15)

    ax.plot(test_lambdas, c2_means, "s-", color=COLOR_C2, lw=2.2, label="C2: Cloud Relay Baseline (Modelled)")
    ax.fill_between(test_lambdas, np.array(c2_means) - 1.96*np.array(c2_stds), np.array(c2_means) + 1.96*np.array(c2_stds), color=COLOR_C2, alpha=0.15)

    # PRD pass bar line: C1 maintains >= 90% success across realistic hospital failure rates
    ax.axhline(0.90, color=COLOR_PASS_BAR, linestyle="--", lw=1.5, label="PRD Pass Bar (≥90% Success)")

    ax.set_title(f"N2: Modelled task success vs. outage rate λ (10 seeds x 10,000 missions, {best_dist} durations)")
    ax.set_xlabel("Outage Arrival Rate λ (outages / hour)")
    ax.set_ylabel("Task Success Probability")
    ax.set_ylim(0.40, 1.05)
    ax.legend(loc="lower left")
    ax.grid(True)
    save_plots(fig, plot_dir, "success_vs_lambda")

    # Write env.json
    env = write_env_json(out_dir, experiment="N2", title="Poisson model of network breakdown", prd="E4",
                         source="modelled", target="Monte Carlo over synthetic inputs, no system run",
                         model=None, seeds={"synthetic_sample": 42, "monte_carlo": list(range(1, 11))})
    # Tail probabilities of the sampled fit at the two survival thresholds: they fix C1 and C2 almost by themselves.
    p_c1_fail_outage = float(best_rv.sf(C1_SURVIVES_BELOW_S, *best_params))
    p_c2_ok_outage = float(best_rv.cdf(C2_SURVIVES_BELOW_S, *best_params))

    measured = (f"model over synthetic inputs: C1 predicted success {c1_at_20 * 100:.2f}% "
                f"(seeds range {c1_at_20_range[0] * 100:.2f}% to {c1_at_20_range[1] * 100:.2f}%) vs C2 {c2_at_20 * 100:.2f}% "
                f"at lambda=20/hr (10 seeds x {N_MISSIONS} missions, {best_dist} durations by AIC); "
                f"KS p={ks_res.pvalue:.4f} on synthetic exponential inter-arrivals")
    notes = [
        f"Inputs are synthetic. The traces in traces/ are labelled 'short synthetic example for local testing' and hold "
        f"{len(outage_durations)} outage(s) in {total_trace_duration:.0f} s, too few to fit; they are parsed and recorded in "
        "outage_model.json (trace_observations) but the fit uses a seeded synthetic sample (see inputs.generator).",
        "The KS test is run on inter-arrivals drawn from an exponential distribution, so a high p-value is expected by "
        "construction: it checks the fitting code, not a real network. No claim about real hospital outages follows from it.",
        f"Success model (assumptions, not measurements): a mission of {mission_duration_s:.0f} s meets Poisson outages; C1 "
        f"fails only if an outage lasts {C1_SURVIVES_BELOW_S:.0f} s or more, C2 if one lasts {C2_SURVIVES_BELOW_S:.0f} s or more. "
        f"Durations are sampled from the AIC-best fit ({best_dist}) with scipy's parameters.",
        f"Under that fit P(outage >= {C1_SURVIVES_BELOW_S:.0f} s) = {p_c1_fail_outage:.1e} and P(outage < {C2_SURVIVES_BELOW_S:.0f} s) = "
        f"{p_c2_ok_outage:.1e}, so C1's success is fixed by the {C1_SURVIVES_BELOW_S:.0f} s assumption and C2's is essentially "
        f"P(no outage in {mission_duration_s:.0f} s) = exp(-lambda x T). The result restates the assumptions; it is not evidence that C1 survives real outages.",
        "Verdict rule: PASS iff KS p >= 0.05 and mean C1 success at lambda=20/hr >= 90%; both are computed above.",
        "An earlier version printed a hard-coded headline (98.4% vs 61.8%) and overlaid hard-coded 'N3 measured' points; "
        "both are removed. N3 is itself an analytical model, not a measurement.",
    ]
    write_readme(out_dir, exp_id="N2", title="Poisson model of network breakdown",
                 claim="A Poisson outage model (fitted to synthetic inputs) predicts that leased edge autonomy (C1) keeps mission success above 90% where a cloud relay (C2) does not.",
                 pass_bar="KS-test p >= 0.05 on exponential inter-arrivals; C1 predicted success >= 90% under hospital outage rates.",
                 measured=measured, verdict="PASS" if verdict_pass else "FAIL", env=env, notes=notes)

    print(f"N2: C1 {c1_at_20:.4f} vs C2 {c2_at_20:.4f} at 20/hr, KS p={ks_res.pvalue:.4f} -> {'PASS' if verdict_pass else 'FAIL'}")

if __name__ == "__main__":
    run_n2()
