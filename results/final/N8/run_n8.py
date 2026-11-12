"""N8: scalability (NFR-3, cloud side): cloud request-to-decision time at 3, 6, 10 and 15 robots.

    python results/final/N8/run_n8.py

For each seed 1 to 10, one simulated hour of SYNTHETIC arrivals (scripts/run_e7.arrivals: Poisson background plus a
ward-round burst, not MIMIC-IV data) goes through the real orchestrator (scripts/run_e7.simulate, offline stand-in
model, 3 clusters) at each fleet size. The metric is the cloud's own wall time per orch.handle_request call, i.e.
request-to-decision latency with the stand-in model; it is not edge decision latency and has no model latency in it.
Each (seed, fleet size) runs K times and keeps the best (lowest) p50/p95, as scripts/run_e7.py does, so a shared
machine's jitter is not read as scaling. Travel and queue waits are modelled.
"""

import os
import json
import csv
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))
sys.path.insert(0, os.getcwd())
from scripts.p4_shared import (
    COLOR_C1, COLOR_C2, COLOR_C3, COLOR_PASS_BAR,
    setup_matplotlib_style, save_plots, write_env_json, write_readme
)
from scripts.run_e7 import simulate, arrivals

K_RUNS = 3          # best-of-K timing per (seed, fleet size); K >= 2
WARMUP_RUNS = 5     # untimed simulations first: on the test laptop the first few runs in a process are ~2x faster
RATIO_BAR = 1.50

def run_n8():
    out_dir = os.path.join("results", "final", "N8")
    plot_dir = os.path.join(out_dir, "plots")
    os.makedirs(plot_dir, exist_ok=True)
    setup_matplotlib_style()

    robot_counts = [3, 6, 10, 15]
    hours = 1.0 # 1 hour simulated window as specified
    wards = [f"w{w}{s}" for w in range(3) for s in "ab"]

    e7_records = []
    summary_rows = []

    # Save representative arrivals for seed 1
    sample_arr = arrivals(hours, 1, wards)
    arr_path = os.path.join(out_dir, "arrival_file.csv")
    with open(arr_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["t_seconds", "priority", "item", "ward"])
        writer.writeheader()
        for a in sample_arr:
            writer.writerow({"t_seconds": round(a["t"], 1), "priority": a["priority"], "item": a["item"], "ward": a["ward"]})

    # Warm-up (discarded). Measured on the test laptop: the same 3-robot simulation's p95 is ~8 ms for the first two to
    # four runs in a process and ~15-20 ms after that (no object or thread growth; a pause does not restore it, so it is
    # the OS/CPU scheduling of a long-running process). Without warm-up, seed 1's baseline lands in the fast state.
    warmup_p95 = [simulate(3, arrivals(hours, 0, wards), 0)["decision_ms_p95"] for _ in range(WARMUP_RUNS)]

    for seed in range(1, 11):
        arr = arrivals(hours, seed, wards)
        seed_results = []
        # Interleave the K runs across fleet sizes (3, 6, 10, 15, 3, 6, ...) so a drift in machine load during the
        # seed affects every size alike instead of inflating the sizes that happen to run last.
        all_runs = {r: [] for r in robot_counts}
        for _ in range(K_RUNS):
            for r in robot_counts:
                all_runs[r].append(simulate(r, arr, seed))
        for r in robot_counts:
            runs = all_runs[r]
            res = runs[0]
            res["decision_ms_p95_runs"] = json.dumps([x["decision_ms_p95"] for x in runs])
            res["replay_identical"] = len({x["log_sha256"] for x in runs}) == 1
            for k in ("decision_ms_p50", "decision_ms_p95"):   # best of K runs
                res[k] = min(x[k] for x in runs)
            res["timing_runs"] = K_RUNS
            res["seed"] = seed
            seed_results.append(res)

        base_res = next(x for x in seed_results if x["robots"] == 3)
        base_p95 = base_res["decision_ms_p95"]

        for r_res in seed_results:
            ratio = round(r_res["decision_ms_p95"] / base_p95, 2) if base_p95 > 0 else 1.0
            r_res["decision_p95_vs_3_robots"] = ratio
            r_res["source"] = "mock_llm"
            e7_records.append(r_res)

        # Summary entry per seed
        r10 = next(x for x in seed_results if x["robots"] == 10)
        r15 = next(x for x in seed_results if x["robots"] == 15)
        summary_rows.append({
            "seed": seed,
            "requests": len(arr),
            "r3_p95_ms": base_p95,
            "r10_p95_ms": r10["decision_ms_p95"],
            "r10_vs_r3_ratio": r10["decision_p95_vs_3_robots"],
            "r15_p95_ms": r15["decision_ms_p95"],
            "r15_vs_r3_ratio": r15["decision_p95_vs_3_robots"],
            "r10_missed_rate": r10["missed_rate"],
            "r15_missed_rate": r15["missed_rate"],
            "pass_nfr3": bool(r10["decision_p95_vs_3_robots"] <= RATIO_BAR and r15["decision_p95_vs_3_robots"] <= RATIO_BAR),
            "decision_logs_identical_across_runs": all(x["replay_identical"] for x in seed_results),
            "source": "mock_llm"
        })

    # Save e7.csv
    df_e7 = pd.DataFrame(e7_records)
    e7_csv_path = os.path.join(out_dir, "e7.csv")
    df_e7.to_csv(e7_csv_path, index=False)

    # Save summary.csv
    df_sum = pd.DataFrame(summary_rows)
    sum_csv_path = os.path.join(out_dir, "summary.csv")
    df_sum.to_csv(sum_csv_path, index=False)

    # Aggregates across seeds for plotting
    agg = df_e7.groupby("robots").agg({
        "decision_ms_p95": ["mean", "std"],
        "wait_s_p95": ["mean", "std"],
        "missed_rate": ["mean", "std"],
        "decision_p95_vs_3_robots": "mean"
    }).reset_index()

    r_vals = agg["robots"].values
    dec_means = agg["decision_ms_p95"]["mean"].values
    dec_stds = agg["decision_ms_p95"]["std"].values
    wait_means = agg["wait_s_p95"]["mean"].values
    miss_means = agg["missed_rate"]["mean"].values

    base_mean = dec_means[0]

    # --- PLOTS ---
    # Plot 1: p95 Edge Latency vs Robot Count with 1.5x band
    fig, ax = plt.subplots(figsize=(6.8, 4.5))
    ax.plot(r_vals, dec_means, "o-", color=COLOR_C1, lw=2.2, label=f"Cloud decision time p95, best of {K_RUNS} (mean of 10 seeds)")
    ax.fill_between(r_vals, dec_means - dec_stds, dec_means + dec_stds, color=COLOR_C1, alpha=0.15)

    # 1.5x threshold band
    threshold_line = base_mean * 1.5
    ax.axhline(threshold_line, color=COLOR_PASS_BAR, linestyle="--", lw=1.5, label=f"NFR-3 Pass Bar (1.5x Baseline: {threshold_line:.2f} ms)")
    ax.axhspan(base_mean, threshold_line, color="#e6f2ff", alpha=0.4, label="Allowed 1.5x Scalability Zone")

    for x_val, y_val in zip(r_vals, dec_means):
        ax.text(x_val, y_val + 0.05, f"{y_val:.2f} ms\n({y_val/base_mean:.2f}x)", ha="center", va="bottom", fontsize=8)

    ax.set_xticks(robot_counts)
    ax.set_title("N8: Cloud request-to-decision time vs fleet size (stand-in model, 3 clusters)")
    ax.set_xlabel("Fleet Size (Robots)")
    ax.set_ylabel("p95 cloud decision time (ms)")
    ax.set_ylim(0, max(threshold_line * 1.3, max(dec_means) * 1.4))
    ax.legend(loc="upper left")
    ax.grid(True)
    save_plots(fig, plot_dir, "p95_latency_scale")

    # Plot 2: Waiting Time and Miss Ratio vs Robot Count
    fig, ax1 = plt.subplots(figsize=(7.0, 4.5))
    color_w = COLOR_C1
    color_m = COLOR_C2

    ax1.set_xlabel("Fleet Size (Robots)")
    ax1.set_ylabel("p95 Waiting Time to Lease (s)", color=color_w)
    l1 = ax1.plot(r_vals, wait_means, "o-", color=color_w, lw=2.0, label="p95 Queue Wait Time (s)")
    ax1.tick_params(axis="y", labelcolor=color_w)
    ax1.set_xticks(robot_counts)
    ax1.grid(True)

    ax2 = ax1.twinx()
    ax2.set_ylabel("Deadline Miss Ratio (%)", color=color_m)
    l2 = ax2.plot(r_vals, miss_means * 100.0, "s--", color=color_m, lw=2.0, label="Deadline Miss Ratio (%)")
    ax2.tick_params(axis="y", labelcolor=color_m)
    ax2.set_ylim(-1, max(15, max(miss_means * 100.0) * 1.5))

    lines = l1 + l2
    labels = [l.get_label() for l in lines]
    ax1.legend(lines, labels, loc="upper right")
    ax1.set_title("N8: Queue Wait Time & Deadline Adherence vs. Fleet Scale")
    save_plots(fig, plot_dir, "waiting_miss_ratio")

    # Plot 3: Arrival rate over the simulated hour
    fig, ax = plt.subplots(figsize=(7.0, 3.8))
    arrival_times = [a["t"] / 60.0 for a in sample_arr] # in minutes
    counts, bins, _ = ax.hist(arrival_times, bins=12, color=COLOR_C3, edgecolor="black", alpha=0.7)
    ax.set_title("N8: Synthetic request arrivals, seed 1 (Poisson background + ward-round burst; not MIMIC-IV)")
    ax.set_xlabel("Simulated Time (minutes)")
    ax.set_ylabel("Requests per 5-min Window")
    ax.grid(axis="y")
    save_plots(fig, plot_dir, "arrival_rate")

    # Write env.json
    env = write_env_json(out_dir, experiment="N8", title="Scalability (cloud side)", prd="NFR-3", source="mock_llm",
                         target="in-process orchestrator via scripts/run_e7.simulate, scale pack with 3 clusters, synthetic arrivals",
                         model="offline stand-in", seeds=list(range(1, 11)), timing_runs_per_point=K_RUNS,
                         warmup_runs=WARMUP_RUNS, warmup_p95_ms=warmup_p95)

    # Metrics for README, all from df_sum
    n_seeds = len(df_sum)
    n_pass = int(df_sum["pass_nfr3"].sum())
    failing = df_sum[~df_sum["pass_nfr3"]]
    r10_avg_ratio = float(np.mean(df_sum["r10_vs_r3_ratio"]))
    r15_avg_ratio = float(np.mean(df_sum["r15_vs_r3_ratio"]))
    worst = float(max(df_sum["r10_vs_r3_ratio"].max(), df_sum["r15_vs_r3_ratio"].max()))
    verdict_pass = n_pass == n_seeds
    measured = (f"cloud request-to-decision p95 (stand-in model, best of {K_RUNS} runs) vs 3 robots: 10 robots mean {r10_avg_ratio:.2f}x, "
                f"15 robots mean {r15_avg_ratio:.2f}x, worst seed {worst:.2f}x; {n_pass}/{n_seeds} seeds within {RATIO_BAR:.2f}x at both sizes"
                + (f" (failing seeds: {', '.join(str(int(x)) for x in failing['seed'])})" if len(failing) else ""))
    notes = [
        "Metric: the cloud orchestrator's own wall time per request (orch.handle_request) with the offline stand-in model, "
        "measured in-process. It is not the edge decision latency that NFR-3 names, and it contains no model latency; the "
        "edge side of NFR-3 is not measured here.",
        "Arrivals are synthetic (scripts/run_e7.arrivals, one simulated hour per seed), not MIMIC-IV. Robot travel, queue waits "
        "and deadline misses are modelled from the scale pack's map, not measured.",
        f"Timing: each (seed, fleet size) runs {K_RUNS} times, interleaved across fleet sizes, and keeps the lowest p50 and p95 (decision_ms_p95_runs in e7.csv "
        "lists all runs); with about 40 to 60 requests per hour the p95 rests on the top 2 or 3 values, so single runs are noisy.",
        f"Warm-up: {WARMUP_RUNS} untimed 3-robot simulations run first (their p95s are in env.json). On the test laptop the first "
        "two to four simulations in a process ran about twice as fast as all later ones; without the warm-up seed 1's 3-robot baseline "
        "fell in the fast phase and seed 1 failed at 1.7x to 2.0x, an artefact of measurement order rather than of fleet size.",
        f"Verdict rule: PASS iff in every seed the 10-robot and 15-robot p95 are both <= {RATIO_BAR:.2f}x the same seed's 3-robot p95.",
    ]
    write_readme(out_dir, exp_id="N8", title="Scalability (cloud side)",
                 claim="The cloud's request-to-decision time at 10 and 15 robots stays within 1.5x of the 3-robot baseline.",
                 pass_bar="p95 edge decision latency at 10+ robots <= 1.5x the 3-robot baseline (NFR-3).",
                 measured=measured, verdict="PASS" if verdict_pass else "FAIL", env=env, notes=notes)

    print(f"N8: {n_pass}/{n_seeds} seeds within {RATIO_BAR}x -> {'PASS' if verdict_pass else 'FAIL'}")

if __name__ == "__main__":
    run_n8()
