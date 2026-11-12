"""N3: network-degradation outcomes for C1, C2, C3 as an ANALYTICAL MODEL (planned as trace replay; not run as one).

    python results/final/N3/run_n3.py

Nothing is replayed and no system code runs: each row comes from closed-form formulas with seeded noise over six
hand-set network profiles (RTT, loss, outage length). Four profiles are named after the synthetic traces in traces/
but the trace files are not read. Key model assumptions decide the outcome: C1 recovery is drawn from U(1.2, 3.5) s
after an outage and C1 succeeds whenever the outage is under 60 s. All rows are `modelled`.
"""

import os
import json
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

def run_n3():
    out_dir = os.path.join("results", "final", "N3")
    raw_dir = os.path.join(out_dir, "raw")
    plot_dir = os.path.join(out_dir, "plots")
    os.makedirs(raw_dir, exist_ok=True)
    os.makedirs(plot_dir, exist_ok=True)
    setup_matplotlib_style()

    tasks = ["T2", "T4", "T5", "T7"]
    configs = ["C1", "C2", "C3"]
    # Hand-set profiles (not read from traces/): name, RTT ms, loss %, outage s.
    traces = [
        {"name": "Healthy", "rtt": 15.0, "loss": 0.0, "outage_s": 0.0},
        {"name": "Corridor", "rtt": 21.0, "loss": 0.5, "outage_s": 0.0},
        {"name": "Lift", "rtt": 240.0, "loss": 8.5, "outage_s": 0.0},
        {"name": "Basement", "rtt": 450.0, "loss": 45.0, "outage_s": 19.0},
        {"name": "N2-Synth-Mild", "rtt": 80.0, "loss": 5.0, "outage_s": 5.0},
        {"name": "N2-Synth-Severe", "rtt": 520.0, "loss": 65.0, "outage_s": 35.0},
    ]

    base_durations = {
        "T2": {"C1": 90.6, "C2": 119.0, "C3": 85.0, "steps": 7, "deadline": 720.0},
        "T4": {"C1": 175.2, "C2": 203.7, "C3": 210.0, "steps": 7, "deadline": 3600.0},
        "T5": {"C1": 108.9, "C2": 137.4, "C3": 160.0, "steps": 8, "deadline": 3600.0},
        "T7": {"C1": 211.4, "C2": 263.2, "C3": 250.0, "steps": 8, "deadline": 1800.0},
    }

    # WAN bytes baseline per task:
    # T7: C1 uses edge filtering -> ~45 KB; C2 streams telemetry/raw images -> ~2400 KB
    wan_bytes_base = {
        "T2": {"C1": 8500, "C2": 32000, "C3": 12000},
        "T4": {"C1": 9200, "C2": 45000, "C3": 14000},
        "T5": {"C1": 14500, "C2": 58000, "C3": 18000},
        "T7": {"C1": 48000, "C2": 2450000, "C3": 1850000},
    }

    rows = []

    for seed in range(1, 11):
        rng = np.random.default_rng(seed * 100 + 42)
        for t_id in tasks:
            t_spec = base_durations[t_id]
            for tr in traces:
                rtt = tr["rtt"]
                loss = tr["loss"]
                outage_s = tr["outage_s"]

                for cfg in configs:
                    # Closed-form model per configuration (assumed formulas, seeded noise)
                    if cfg == "C1":
                        # Autonomous under lease: Link degradation only adds small queue drain time
                        recovery_s = round(float(rng.uniform(1.2, 3.5) if outage_s > 0 else rng.uniform(0.1, 0.5)), 2)
                        stalls = 0
                        completion_s = round(float(t_spec["C1"] + recovery_s + rng.normal(0, 1.5)), 1)
                        success = 1 if completion_s <= t_spec["deadline"] and (outage_s < 60) else 0
                        deadline_met = 1 if completion_s <= t_spec["deadline"] else 0
                        wan_b = int(wan_bytes_base[t_id]["C1"] * rng.uniform(0.95, 1.05))

                    elif cfg == "C2":
                        # Cloud Relay: Every step blocks on WAN round-trip
                        recovery_s = round(float(outage_s + rng.uniform(12.0, 24.0) if outage_s > 0 else (rtt / 1000.0 * 5.0)), 2)
                        stalls = int(outage_s // 8 + (1 if loss > 10 else 0))
                        extra_delay = (t_spec["steps"] * (rtt / 1000.0) * 3.0) + recovery_s
                        completion_s = round(float(t_spec["C2"] + extra_delay + rng.normal(0, 4.0)), 1)
                        # Fails if stalls / timeout disconnect
                        prob_success = max(0.0, 1.0 - (loss / 80.0) - (outage_s / 50.0))
                        success = 1 if rng.uniform() < prob_success and completion_s <= t_spec["deadline"] else 0
                        deadline_met = 1 if completion_s <= t_spec["deadline"] and success == 1 else 0
                        wan_b = int(wan_bytes_base[t_id]["C2"] * rng.uniform(0.95, 1.08))

                    else: # C3
                        # Centralized rules
                        recovery_s = round(float(outage_s + rng.uniform(8.0, 18.0) if outage_s > 0 else (rtt / 1000.0 * 2.0)), 2)
                        stalls = int(outage_s // 10)
                        extra_delay = recovery_s + (rtt / 1000.0 * 2.0)
                        completion_s = round(float(t_spec["C3"] + extra_delay + rng.normal(0, 3.0)), 1)
                        prob_success = max(0.0, 0.95 - (loss / 90.0) - (outage_s / 60.0))
                        success = 1 if rng.uniform() < prob_success and completion_s <= t_spec["deadline"] else 0
                        deadline_met = 1 if completion_s <= t_spec["deadline"] and success == 1 else 0
                        wan_b = int(wan_bytes_base[t_id]["C3"] * rng.uniform(0.95, 1.05))

                    rows.append({
                        "seed": seed,
                        "task": t_id,
                        "config": cfg,
                        "trace": tr["name"],
                        "rtt_ms": rtt,
                        "loss_pct": loss,
                        "outage_s": outage_s,
                        "success": success,
                        "deadline_met": deadline_met,
                        "completion_time_s": max(10.0, completion_s),
                        "recovery_time_s": recovery_s,
                        "stalls": stalls,
                        "wan_bytes": wan_b,
                        "source": "modelled"
                    })

    df = pd.DataFrame(rows)
    summary_path = os.path.join(out_dir, "summary.csv")
    df.to_csv(summary_path, index=False)

    # Model description in raw/ (the old replay_harness_meta.json described a harness that never existed)
    model_meta = {
        "experiment": "N3 analytical network-degradation model (not trace replay)",
        "rows": len(rows),
        "configurations": configs,
        "tasks": tasks,
        "profiles": traces,
        "profiles_note": "hand-set constants; the files in traces/ are not read",
        "seeds": list(range(1, 11)),
        "rng": "numpy default_rng(seed * 100 + 42)",
        "c1_model": "recovery ~ U(1.2, 3.5) s if outage else U(0.1, 0.5) s; success = completion <= deadline and outage < 60 s",
        "c2_model": "recovery = outage + U(12, 24) s; success ~ Bernoulli(max(0, 1 - loss/80 - outage/50)) and deadline",
        "c3_model": "recovery = outage + U(8, 18) s; success ~ Bernoulli(max(0, 0.95 - loss/90 - outage/60)) and deadline",
        "wan_bytes": "hand-set per task and configuration, x U(0.95, 1.05..1.08)",
    }
    with open(os.path.join(raw_dir, "model_meta.json"), "w", encoding="utf-8") as f:
        json.dump(model_meta, f, indent=2)
        f.write("\n")
    stale_meta = os.path.join(raw_dir, "replay_harness_meta.json")
    if os.path.exists(stale_meta):
        os.remove(stale_meta)

    # --- PLOTS ---
    # Plot 1: Success vs Mean Loss
    fig, ax = plt.subplots(figsize=(6.5, 4.5))
    loss_groups = df.groupby(["config", "loss_pct"])["success"].mean().reset_index()
    for cfg, col, marker in [("C1", COLOR_C1, "o"), ("C2", COLOR_C2, "s"), ("C3", COLOR_C3, "^")]:
        sub = loss_groups[loss_groups["config"] == cfg].sort_values("loss_pct")
        ax.plot(sub["loss_pct"], sub["success"] * 100.0, f"{marker}-", color=col, lw=2.2, label=f"{cfg} (modelled)")

    ax.axhline(90.0, color=COLOR_PASS_BAR, linestyle="--", lw=1.5, label="PRD Pass Bar (≥90% Success)")
    ax.set_title("N3 (analytical model): Task success rate vs. packet loss")
    ax.set_xlabel("Mean Packet Loss (%)")
    ax.set_ylabel("Success Rate (%)")
    ax.set_ylim(-5, 105)
    ax.legend(loc="lower left")
    ax.grid(True)
    save_plots(fig, plot_dir, "success_vs_loss")

    # Plot 2: Recovery Time Box Plot per trace (C1 vs C2)
    fig, ax = plt.subplots(figsize=(7.5, 4.8))
    trace_names = [t["name"] for t in traces if t["outage_s"] > 0] # traces with outages
    c1_rec = [df[(df["config"] == "C1") & (df["trace"] == tr)]["recovery_time_s"].values for tr in trace_names]
    c2_rec = [df[(df["config"] == "C2") & (df["trace"] == tr)]["recovery_time_s"].values for tr in trace_names]

    positions = np.arange(len(trace_names))
    width = 0.35
    bp1 = ax.boxplot(c1_rec, positions=positions - width/2, widths=width, patch_artist=True,
                     boxprops=dict(facecolor=COLOR_C1, color=COLOR_C1), medianprops=dict(color="white", lw=2))
    bp2 = ax.boxplot(c2_rec, positions=positions + width/2, widths=width, patch_artist=True,
                     boxprops=dict(facecolor=COLOR_C2, color=COLOR_C2), medianprops=dict(color="white", lw=2))

    ax.axhline(60.0, color=COLOR_PASS_BAR, linestyle="--", lw=1.5, label="PRD Pass Bar (≤60s Recovery)")
    ax.set_title("N3 (analytical model): Recovery time after outage by profile (C1 vs. C2)")
    ax.set_xticks(positions)
    ax.set_xticklabels(trace_names)
    ax.set_xlabel("Network profile (hand-set)")
    ax.set_ylabel("Recovery Time (seconds)")
    ax.legend([bp1["boxes"][0], bp2["boxes"][0]], ["C1 (Nimbus Edge)", "C2 (Cloud Relay)"], loc="upper left")
    ax.grid(True)
    save_plots(fig, plot_dir, "recovery_time_box")

    # Plot 3: Completion time vs RTT
    fig, ax = plt.subplots(figsize=(6.5, 4.5))
    rtt_groups = df[df["task"] == "T2"].groupby(["config", "rtt_ms"])["completion_time_s"].mean().reset_index()
    for cfg, col, marker in [("C1", COLOR_C1, "o"), ("C2", COLOR_C2, "s"), ("C3", COLOR_C3, "^")]:
        sub = rtt_groups[rtt_groups["config"] == cfg].sort_values("rtt_ms")
        ax.plot(sub["rtt_ms"], sub["completion_time_s"], f"{marker}-", color=col, lw=2.0, label=f"{cfg} (T2 Urgent)")

    ax.set_title("N3 (analytical model): Completion time vs. RTT (task T2)")
    ax.set_xlabel("Mean Round-Trip Time (ms)")
    ax.set_ylabel("Completion Time (seconds)")
    ax.legend(loc="upper left")
    ax.grid(True)
    save_plots(fig, plot_dir, "completion_vs_rtt")

    # Plot 4: WAN bytes per task (T7 Edge Filtering Comparison)
    fig, ax = plt.subplots(figsize=(6.5, 4.5))
    wan_t7 = df[df["task"] == "T7"].groupby("config")["wan_bytes"].mean() / 1024.0 # in KB
    bars = ax.bar(["C1 (Edge Filtered)", "C2 (Raw Telemetry)", "C3 (Centralized)"],
                  [wan_t7.get("C1", 48), wan_t7.get("C2", 2450), wan_t7.get("C3", 1850)],
                  color=[COLOR_C1, COLOR_C2, COLOR_C3], edgecolor="black", width=0.55)
    for b in bars:
        h = b.get_height()
        ax.text(b.get_x() + b.get_width()/2., h + 30, f"{h:.0f} KB", ha="center", va="bottom", fontsize=9, fontweight="bold")

    ax.set_title("N3 (analytical model): WAN bytes in survey task T7 (hand-set baselines)")
    ax.set_ylabel("WAN Data Transferred (KB)")
    ax.set_ylim(0, 3000)
    ax.grid(axis="y")
    save_plots(fig, plot_dir, "wan_bytes_per_task")

    # Write env.json
    env = write_env_json(out_dir, experiment="N3", title="Network degradation (analytical model; planned as trace replay)",
                         prd="FR-6, NFR-2", source="modelled", target="closed-form model with seeded noise, no system run",
                         model=None, seeds=list(range(1, 11)))

    # Key metrics, computed from the rows. Recovery statistics use outage rows only (rows with no outage have no
    # recovery to measure; the old mean mixed them in).
    c1 = df[df["config"] == "C1"]
    c1_out = c1[c1["outage_s"] > 0]
    c1_succ_n, c1_n = int(c1["success"].sum()), len(c1)
    c1_rec_mean = float(c1_out["recovery_time_s"].mean())
    c1_rec_median = float(np.percentile(c1_out["recovery_time_s"], 50))
    c1_rec_p95 = float(np.percentile(c1_out["recovery_time_s"], 95))
    c1_rec_max = float(c1_out["recovery_time_s"].max())
    c2_out = df[(df["config"] == "C2") & (df["outage_s"] > 0)]
    c2_succ = float(df[df["config"] == "C2"]["success"].mean() * 100.0)
    c3_succ = float(df[df["config"] == "C3"]["success"].mean() * 100.0)
    recovery_ok = c1_rec_p95 <= 60.0
    success_ok = c1_succ_n / c1_n >= 0.90
    verdict_pass = recovery_ok and success_ok
    outage_profiles = sorted(c1_out["trace"].unique())

    measured = (f"analytical model, not a measurement: C1 recovery over {len(c1_out)} outage rows ({', '.join(outage_profiles)}) "
                f"median {c1_rec_median:.2f} s, mean {c1_rec_mean:.2f} s, p95 {c1_rec_p95:.2f} s (<= 60 s); "
                f"C1 success {c1_succ_n}/{c1_n} ({100.0 * c1_succ_n / c1_n:.1f}%) vs C2 {c2_succ:.1f}%, C3 {c3_succ:.1f}%; "
                "both C1 numbers are fixed by the model's formulas")
    notes = [
        "This is not trace replay: no trace file is opened and no Nimbus code runs. Every row is computed from closed-form "
        "formulas with seeded noise over six hand-set profiles (see raw/model_meta.json). The four profiles named after "
        "traces are hand-set constants, not read from traces/.",
        f"The C1 results hold by construction: C1 recovery is drawn from U(1.2, 3.5) s whenever the profile has an outage "
        f"(so its p95 cannot exceed 3.5 s), and C1 counts as a success whenever the outage is under 60 s, which every profile "
        f"is (longest {df['outage_s'].max():.0f} s). The PASS restates these assumptions; it is not evidence for FR-6 or NFR-2.",
        f"Recovery statistics are over outage rows only (C1: {len(c1_out)} rows, C2: {len(c2_out)} rows); earlier versions "
        "averaged in rows with no outage.",
        "Verdict rule: PASS iff C1 recovery p95 over outage rows <= 60 s and C1 success >= 90%. For measured recovery and "
        "safe parking see R7 and R9.",
        "WAN bytes per task are hand-set baselines times seeded noise, not measured traffic.",
    ]
    write_readme(out_dir, exp_id="N3", title="Network degradation (analytical model; planned as trace replay)",
                 claim="Under an analytical model of six network profiles, leased edge autonomy (C1) recovers from outages within NFR-2's minute and keeps success >= 90%, unlike C2 and C3.",
                 pass_bar="Normal operation resumed within 60-120 s (NFR-2); Success >= 90%.",
                 measured=measured, verdict="PASS" if verdict_pass else "FAIL", env=env, notes=notes)

    print(f"N3: C1 recovery p95 (outage rows) {c1_rec_p95:.2f} s, C1 success {c1_succ_n}/{c1_n} -> {'PASS' if verdict_pass else 'FAIL'}")

if __name__ == "__main__":
    run_n3()
