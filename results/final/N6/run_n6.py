"""N6: audit replay and determinism (FR-20, NFR-6).

    python results/final/N6/run_n6.py

For each seed 1 to 10, scripts/replay_check.scenario(seed) runs the real orchestrator on a fixed clock with the offline
stand-in model and returns its decision log. Run A is in this process; run B is a separate Python process with
PYTHONHASHSEED=42. The two logs are compared byte for byte (sha256 and a unified diff). The swimlane plot draws the
actual decision rows of seed 7. Every count comes from those rows.
"""

import os
import json
from collections import Counter
import hashlib
import difflib
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
from scripts.replay_check import scenario, digest, compare

def run_n6():
    out_dir = os.path.join("results", "final", "N6")
    plot_dir = os.path.join(out_dir, "plots")
    os.makedirs(plot_dir, exist_ok=True)
    setup_matplotlib_style()

    summary_rows = []
    replay_data = {}

    # 1. Run 10 seeded scenarios (seeds 1 to 10)
    # Compare in-process run A and independent-process run B (with PYTHONHASHSEED=42) for each to prove determinism
    import subprocess
    all_diffs = []
    for seed in range(1, 11):
        # Run A: in-process
        rows_a = scenario(seed)
        hash_a = digest(rows_a)

        # Run B: independent Python subprocess with distinct PYTHONHASHSEED
        sub_code = (
            f"import json; from scripts.replay_check import scenario, digest; "
            f"rows = scenario({seed}); print(json.dumps({{'hash': digest(rows), 'rows': rows}}))"
        )
        env = os.environ.copy()
        env["PYTHONHASHSEED"] = "42"
        sub_proc = subprocess.run(
            [sys.executable, "-c", sub_code],
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        sub_res = json.loads(sub_proc.stdout)
        rows_b = sub_res["rows"]
        hash_b = sub_res["hash"]

        diff = compare(rows_a, rows_b)
        diff_len = len(diff)
        all_diffs.extend(diff)

        decisions = Counter((r.get("output") or {}).get("decision") for r in rows_a)
        replay_data[f"seed_{seed}"] = {
            "decision_rows_count": len(rows_a),
            "decisions_by_type": dict(sorted((str(k), v) for k, v in decisions.items())),
            "leases_issued": decisions.get("issue_lease", 0),
            "sha256": hash_a,
            "deterministic": (hash_a == hash_b),
            "sample_timeline": rows_a[:4]
        }

        summary_rows.append({
            "seed": seed,
            "scenario": "E3_E4_composite",
            "decision_rows": len(rows_a),
            "sha256_hash": hash_a,
            "sha256_hash_run_b": hash_b,
            "deterministic": (hash_a == hash_b),
            "diff_lines": diff_len,
            "leases_issued": decisions.get("issue_lease", 0),
            "replayed_successfully": (hash_a == hash_b and diff_len == 0),
            "source": "simulated"
        })

    # Save e6_replay.json
    with open(os.path.join(out_dir, "e6_replay.json"), "w", encoding="utf-8") as f:
        json.dump(replay_data, f, indent=2)

    # Save e6_seed_diff.txt (must be empty or indicate zero diff)
    diff_file_path = os.path.join(out_dir, "e6_seed_diff.txt")
    with open(diff_file_path, "w", encoding="utf-8") as f:
        if not all_diffs:
            f.write("") # exactly empty diff
        else:
            f.write("\n".join(all_diffs))

    # Save summary.csv
    df_sum = pd.DataFrame(summary_rows)
    df_sum.to_csv(os.path.join(out_dir, "summary.csv"), index=False)

    # --- PLOT: swimlane of the real decision rows of one seed (seed 7), in log order ---
    sample_seed = 7
    sample_rows = scenario(sample_seed)
    lanes = list(dict.fromkeys(r["who"] for r in sample_rows))
    lane_y = {w: i for i, w in enumerate(lanes)}
    fig, ax = plt.subplots(figsize=(9.5, 3.2 + 0.6 * len(lanes)))
    palette = [COLOR_C1, COLOR_C2, "#2ca02c", COLOR_C3, "#9467bd"]
    for idx, r in enumerate(sample_rows):
        y = lane_y[r["who"]]
        ax.scatter(idx, y, color=palette[y % len(palette)], s=70, zorder=4, edgecolors="black", linewidth=0.6)
        decision = (r.get("output") or {}).get("decision")
        lv = r.get("lease_version")
        ax.text(idx, y + 0.12, f"{decision}" + (f" v{lv}" if lv is not None else ""), rotation=35, ha="left", va="bottom", fontsize=7, color="#222222")
    ax.step(range(len(sample_rows)), [lane_y[r["who"]] for r in sample_rows], where="post", color="#888888", linestyle="--", lw=1.0, zorder=2)
    ax.set_yticks(list(lane_y.values()))
    ax.set_yticklabels([f"who = {w}" for w in lanes])
    ax.set_ylim(-0.5, len(lanes) - 0.5 + 0.9)
    ax.set_xlim(-1, len(sample_rows) + 2)
    ax.set_xlabel(f"Decision-log row (order in the log; the scenario runs on a fixed clock), seed {sample_seed}")
    ax.set_title(f"N6: Decision log of seed {sample_seed} ({len(sample_rows)} rows, replayed byte-identically)")
    ax.xaxis.set_major_locator(plt.MaxNLocator(integer=True))
    ax.grid(axis="x", linestyle=":", alpha=0.6)
    save_plots(fig, plot_dir, "timeline_swimlane")

    # Write env.json
    env = write_env_json(out_dir, experiment="N6", title="Audit replay and determinism", prd="FR-20, NFR-6",
                         source="simulated", target="in-process orchestrator on a fixed clock via scripts/replay_check.scenario, two processes per seed",
                         model="offline stand-in", seeds=list(range(1, 11)))

    df_s = pd.DataFrame(summary_rows)
    n_seeds = len(df_s)
    n_identical = int((df_s["deterministic"] & (df_s["diff_lines"] == 0)).sum())
    diff_bytes = os.path.getsize(diff_file_path)
    total_rows = int(df_s["decision_rows"].sum())
    verdict_pass = n_identical == n_seeds and diff_bytes == 0
    measured = (f"{n_identical}/{n_seeds} seeds byte-identical between two processes (sha256 equal, {diff_bytes} diff bytes in "
                f"e6_seed_diff.txt); {total_rows} decision rows in total ({int(df_s['decision_rows'].min())} to "
                f"{int(df_s['decision_rows'].max())} per seed), {int(df_s['leases_issued'].sum())} lease issues")
    notes = [
        "What is checked: re-running a seeded scenario (8 requests through the orchestrator with the offline model, fixed "
        "clock) in a separate process with a different PYTHONHASHSEED gives the same decision log, byte for byte.",
        "The decision rows compared are who/inputs/output/lease_version (scripts/replay_check.scenario); timestamps are not "
        "part of them. Replaying a log from a deployed run, or with the real Bedrock model, is not tested here.",
        "The swimlane is drawn from seed 7's actual rows (x = row order in the log). Earlier versions drew a hand-written "
        "event list and reported a literal '100% timeline reconstruction'; both are removed.",
        "Verdict rule: PASS iff every seed's two runs have equal sha256 and an empty diff.",
    ]
    write_readme(out_dir, exp_id="N6", title="Audit replay and determinism",
                 claim="A seeded scenario's decision log is reproduced byte for byte when the scenario is re-run in another process.",
                 pass_bar="Every timeline replays (FR-20); seeded reruns are byte-identical (empty diff) (NFR-6).",
                 measured=measured, verdict="PASS" if verdict_pass else "FAIL", env=env, notes=notes)

    print(f"N6: {n_identical}/{n_seeds} seeds identical, {diff_bytes} diff bytes -> {'PASS' if verdict_pass else 'FAIL'}")

if __name__ == "__main__":
    run_n6()
