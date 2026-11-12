"""N9: cost per task (NFR-4), priced from the model calls and tokens measured in C9.

    python results/final/N9/run_n9.py

Inputs: results/final/C9/raw/tasks.jsonl (read only): one record per task from the real-Bedrock C9 run (Nova Lite,
calls and tokens from the model's usage fields). Nothing is drawn at random and no AWS API is called. Every priced
row is `modelled`: the call and token counts are measured (C9), the dollars are those counts times list prices.
"""

import os
import json
import datetime
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

C9_DIR = os.path.join("results", "final", "C9")
CONFIGS = ["C1", "C2", "C3"]

# Unit prices (USD). Bedrock Nova Lite per token; Fargate per vCPU-hour and per GB-hour, converted to per second
# below. These are the constants the project already uses (docs/cost-accounting-audit.md); the Fargate rates match
# AWS's published us-east-1 Linux/x86 list price (ap-south-1 is somewhat higher). Not re-checked for this run.
PRICES = {
    "p_in_per_token": 0.06 / 1e6,          # Nova Lite input: $0.06 per 1M tokens
    "p_out_per_token": 0.24 / 1e6,         # Nova Lite output: $0.24 per 1M tokens
    "p_fargate_vcpu_hour": 0.04048,        # per vCPU-hour
    "p_fargate_gb_hour": 0.004445,         # per GB-hour
}
# Task size from infra/terraform/main.tf (aws_ecs_task_definition: cpu = 512, memory = 1024).
FARGATE_VCPU = 512 / 1024
FARGATE_GB = 1024 / 1024


def run_n9():
    out_dir = os.path.join("results", "final", "N9")
    plot_dir = os.path.join(out_dir, "plots")
    os.makedirs(plot_dir, exist_ok=True)
    setup_matplotlib_style()

    # 1. Measured inputs: C9's per-task records (real Bedrock).
    with open(os.path.join(C9_DIR, "raw", "tasks.jsonl"), encoding="utf-8") as f:
        c9 = [json.loads(line) for line in f if line.strip()]
    with open(os.path.join(C9_DIR, "env.json"), encoding="utf-8") as f:
        c9_env = json.load(f)
    started = datetime.datetime.strptime(c9_env["started_utc"], "%Y-%m-%dT%H:%M:%SZ")
    finished = datetime.datetime.strptime(c9_env["finished_utc"], "%Y-%m-%dT%H:%M:%SZ")
    c9_wall_s = (finished - started).total_seconds()

    # Fargate share per task (an assumption, stated): the service is always on (desired_count = 1), so its cost per
    # task depends on throughput. We charge each task the container time the C9 run itself used per task: C9's wall
    # clock (started_utc to finished_utc) divided by the tasks it ran, the same for every configuration.
    fargate_s_per_task = c9_wall_s / len(c9)
    fargate_rate_per_s = (FARGATE_VCPU * PRICES["p_fargate_vcpu_hour"] + FARGATE_GB * PRICES["p_fargate_gb_hour"]) / 3600.0

    cost_records = []
    for r in c9:
        bedrock = r["tokens_in"] * PRICES["p_in_per_token"] + r["tokens_out"] * PRICES["p_out_per_token"]
        fargate = fargate_s_per_task * fargate_rate_per_s
        cost_records.append({
            "config": r["mode"], "task": r["task"], "repeat": r["repeat"], "c9_task_id": r["task_id"],
            "llm_calls": r["calls"], "tokens_in": r["tokens_in"], "tokens_out": r["tokens_out"],
            "tokens_estimated": r.get("tokens_estimated"), "final_status": r.get("final_status"),
            "bedrock_cost_usd": bedrock, "fargate_cost_usd": fargate, "total_cost_usd": bedrock + fargate,
            "source": "modelled (C9 measured counts x list prices)",
        })
    df_cost = pd.DataFrame(cost_records)
    df_cost.to_csv(os.path.join(out_dir, "cost.csv"), index=False)

    # 2. Summary per configuration and task type, then per configuration over all tasks.
    summary_rows = []
    for cfg in CONFIGS:
        sub_cfg = df_cost[df_cost["config"] == cfg]
        for task in sorted(sub_cfg["task"].unique()) + ["all"]:
            sub = sub_cfg if task == "all" else sub_cfg[sub_cfg["task"] == task]
            summary_rows.append({
                "config": cfg, "task": task, "tasks": len(sub),
                "calls_per_task": round(sub["llm_calls"].mean(), 4),
                "tokens_in_per_task": round(sub["tokens_in"].mean(), 1),
                "tokens_out_per_task": round(sub["tokens_out"].mean(), 1),
                "bedrock_usd_per_task": round(sub["bedrock_cost_usd"].mean(), 8),
                "fargate_usd_per_task": round(sub["fargate_cost_usd"].mean(), 8),
                "total_usd_per_task": round(sub["total_cost_usd"].mean(), 8),
                "source": "modelled (C9 measured counts x list prices)",
            })
    df_sum = pd.DataFrame(summary_rows)
    df_sum.to_csv(os.path.join(out_dir, "summary.csv"), index=False)

    allrow = df_sum[df_sum["task"] == "all"].set_index("config")
    c1_calls, c2_calls = allrow.loc["C1", "calls_per_task"], allrow.loc["C2", "calls_per_task"]
    ratio_pct = 100.0 * c1_calls / c2_calls
    nfr4_pass = ratio_pct <= 50.0

    # Bootstrap 95% interval of the call ratio (resampling C9 tasks within each configuration).
    rng = np.random.default_rng(9)
    c1_v = df_cost[df_cost["config"] == "C1"]["llm_calls"].to_numpy()
    c2_v = df_cost[df_cost["config"] == "C2"]["llm_calls"].to_numpy()
    boots = [100.0 * rng.choice(c1_v, c1_v.size).mean() / rng.choice(c2_v, c2_v.size).mean() for _ in range(2000)]
    ratio_lo, ratio_hi = np.percentile(boots, [2.5, 97.5])

    formula_sheet = {
        "prd_formula": "Cost = [T_in*p_in + T_out*p_out + F*p_fargate + M*p_iot + W*p_ddb + Q*p_sqs + S*p_s3 + D*p_transfer + G*p_apigw + K*p_cw] / N_tasks",
        "terms_priced": ["T_in*p_in", "T_out*p_out", "F*p_fargate"],
        "terms_not_priced": "M, W, Q, S, D, G, K (IoT, DynamoDB, SQS, S3, transfer, API Gateway, CloudWatch): C9 did not log these counters per task, so they are left out rather than guessed.",
        "pricing_parameters_usd": PRICES,
        "fargate_task_size": {"vcpu": FARGATE_VCPU, "memory_gb": FARGATE_GB, "from": "infra/terraform/main.tf cpu=512, memory=1024"},
        "fargate_rate_usd_per_second": fargate_rate_per_s,
        "fargate_seconds_per_task_assumed": fargate_s_per_task,
        "fargate_seconds_basis": f"C9 wall clock {c9_env['started_utc']} to {c9_env['finished_utc']} ({c9_wall_s:.0f} s) / {len(c9)} tasks",
        "inputs": {"file": "results/final/C9/raw/tasks.jsonl", "tasks": len(c9), "c9_source": c9_env.get("source"),
                   "c9_model": c9_env.get("model"), "c9_commit": c9_env.get("git_commit")},
        "averages_per_task_usd": {c: float(allrow.loc[c, "total_usd_per_task"]) for c in CONFIGS},
        "nfr4": {"c1_calls_per_task": float(c1_calls), "c2_calls_per_task": float(c2_calls),
                 "ratio_pct": float(ratio_pct), "ratio_pct_bootstrap_95ci": [float(ratio_lo), float(ratio_hi)],
                 "pass_threshold_pct": 50.0, "pass": bool(nfr4_pass)},
    }
    with open(os.path.join(out_dir, "cost_formula_sheet.json"), "w", encoding="utf-8") as f:
        json.dump(formula_sheet, f, indent=2)
        f.write("\n")

    # --- PLOTS ---
    # Plot 1: stacked cost per task by priced term
    fig, ax = plt.subplots(figsize=(7.5, 4.8))
    cfg_names = ["C1\n(Nimbus Edge)", "C2\n(Cloud Relay)", "C3\n(Central Rules)"]
    bottom = np.zeros(len(CONFIGS))
    for label, col_key, bar_color in [("Bedrock (Nova Lite tokens)", "bedrock_usd_per_task", "#8c564b"),
                                      ("ECS Fargate (0.5 vCPU, 1 GB share)", "fargate_usd_per_task", "#1f77b4")]:
        vals = np.array([allrow.loc[c, col_key] * 1000.0 for c in CONFIGS])  # milli-USD
        ax.bar(cfg_names, vals, bottom=bottom, width=0.50, label=label, color=bar_color, edgecolor="black", linewidth=0.5)
        bottom += vals
    for i, total_val in enumerate(bottom):
        ax.text(i, total_val * 1.02, f"${total_val / 1000.0:.6f}", ha="center", va="bottom", fontweight="bold", fontsize=9)
    ax.set_title("N9: Modelled cost per task (C9 measured calls/tokens x list prices)")
    ax.set_ylabel("Cost per task (milli-USD)")
    ax.set_ylim(0, max(bottom) * 1.25)
    ax.legend(loc="upper right")
    ax.grid(axis="y")
    save_plots(fig, plot_dir, "cost_per_task_stacked")

    # Plot 2: model calls per task by task type (measured in C9), with the NFR-4 bar at 50% of C2's mean
    fig, ax = plt.subplots(figsize=(7.5, 4.6))
    tasks = sorted(df_cost["task"].unique())
    x = np.arange(len(tasks))
    w = 0.27
    for i, (cfg, col) in enumerate([("C1", COLOR_C1), ("C2", COLOR_C2), ("C3", COLOR_C3)]):
        vals = [df_sum[(df_sum["config"] == cfg) & (df_sum["task"] == t)]["calls_per_task"].iloc[0] for t in tasks]
        ax.bar(x + (i - 1) * w, vals, width=w, color=col, edgecolor="black", linewidth=0.5,
               label=f"{cfg} (mean {allrow.loc[cfg, 'calls_per_task']:.2f})")
    ax.axhline(0.5 * c2_calls, color=COLOR_PASS_BAR, linestyle="--", lw=1.5, label=f"NFR-4 bar: 50% of C2 mean ({0.5 * c2_calls:.2f})")
    ax.set_xticks(x)
    ax.set_xticklabels(tasks)
    ax.set_xlabel("Task scenario (C9; no T6 in C9)")
    ax.set_ylabel("Cloud model calls per task")
    ax.set_title(f"N9: Model calls per task from C9 (C1/C2 = {ratio_pct:.1f}%)")
    ax.legend(loc="upper left")
    ax.grid(axis="y")
    save_plots(fig, plot_dir, "calls_per_task_c9")

    # The old success-vs-cost plot drew hard-coded success rates; it is no longer produced.
    for ext in ("png", "svg"):
        stale = os.path.join(plot_dir, f"success_vs_cost.{ext}")
        if os.path.exists(stale):
            os.remove(stale)

    env = write_env_json(out_dir, experiment="N9", title="Cost per task", prd="NFR-4",
                         source="modelled", target=f"offline: prices results/final/C9/raw/tasks.jsonl, {len(c9)} tasks",
                         model=f"none called here; C9 counts came from {c9_env.get('model')}",
                         seeds={"bootstrap": 9}, inputs=["results/final/C9/raw/tasks.jsonl", "results/final/C9/env.json"])

    measured = (f"from C9's {len(c9)} real-Bedrock tasks: calls per task C1 {c1_calls:.2f}, C2 {c2_calls:.2f}, "
                f"C3 {allrow.loc['C3', 'calls_per_task']:.2f}; C1/C2 = {ratio_pct:.1f}% (bootstrap 95% CI {ratio_lo:.1f}% to {ratio_hi:.1f}%); "
                f"modelled cost per task (Bedrock tokens + Fargate share) C1 ${allrow.loc['C1', 'total_usd_per_task']:.6f}, "
                f"C2 ${allrow.loc['C2', 'total_usd_per_task']:.6f}, C3 ${allrow.loc['C3', 'total_usd_per_task']:.6f}")
    notes = [
        "Call and token counts are C9's measurements (results/final/C9/raw/tasks.jsonl, real Bedrock Nova Lite, "
        f"commit {c9_env.get('git_commit')}); this runner only prices them. The NFR-4 verdict is C9's measured ratio, recomputed here.",
        f"Priced terms: Bedrock tokens (${PRICES['p_in_per_token'] * 1e6:.2f} / ${PRICES['p_out_per_token'] * 1e6:.2f} per 1M in/out) and a Fargate share "
        f"(0.5 vCPU x ${PRICES['p_fargate_vcpu_hour']}/h + 1 GB x ${PRICES['p_fargate_gb_hour']}/h, divided by 3600 s/h). "
        "The Fargate rates are AWS's us-east-1 list prices as used in docs/cost-accounting-audit.md; ap-south-1 is somewhat higher.",
        f"Fargate share assumption: the service is always on, so its per-task cost depends on throughput. Each task is charged "
        f"{fargate_s_per_task:.2f} s of container time, the C9 run's wall clock ({c9_wall_s:.0f} s) divided by its {len(c9)} tasks; "
        "the same for every configuration (C9 does not split time by configuration). At lower throughput the share is larger.",
        "Not priced: IoT, DynamoDB, SQS, S3, transfer, API Gateway and CloudWatch terms, because C9 did not log those counters per task.",
        "C9 has no T6 tasks; T5 tasks stayed 'leased' in C9 (the harness does not finish them), so they count calls but not completion.",
        "No AWS API (CloudWatch, Cost Explorer) is called and no billing data is stored; earlier versions of this runner did both and drew counts at random.",
    ]
    write_readme(out_dir, exp_id="N9", title="Cost per task",
                 claim="C1 needs at most half the cloud model calls of C2 (NFR-4), and the cost per task can be reported for C1, C2 and C3 from measured counts.",
                 pass_bar="C1 model calls <= 50% of C2 (NFR-4); Cost per task reported for all configurations.",
                 measured=measured, verdict="PASS" if nfr4_pass else "FAIL", env=env, notes=notes)

    print(f"N9: C1/C2 calls = {ratio_pct:.1f}% -> {'PASS' if nfr4_pass else 'FAIL'}")


if __name__ == "__main__":
    run_n9()
