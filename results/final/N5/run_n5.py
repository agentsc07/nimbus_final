"""N5: selective sharing (FR-11): which clusters MapState.affected_clusters says to tell about a map event.

    python results/final/N5/run_n5.py

Per seed (1 to 10) the seed's RNG draws 30 events (zone from all 15 topology nodes, event type) and the live leases
(each cluster's lease routes through 2 to 4 random zones, so a lease can cross into the other wing). The system under
test is cloud.mapstate.MapState.affected_clusters; the expected set is computed from the FR-11 rule (cluster area or
shared area, or a live lease routed through the zone) directly from the pack's topology document.
"""

import os
import json
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from datetime import datetime, timezone
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))
sys.path.insert(0, os.getcwd())
from scripts.p4_shared import (
    COLOR_C1, COLOR_C2, COLOR_C3, COLOR_PASS_BAR,
    setup_matplotlib_style, save_plots, write_env_json, write_readme
)
from cloud.pack import Pack
from cloud.topology import Topology
from cloud.mapstate import MapState

class MockRepo:
    def __init__(self, leases):
        self._leases = leases
    def live_leases(self):
        return self._leases

def independent_ground_truth(zone: str, leases: list[dict], pack: Pack) -> set[str]:
    """Independent ground-truth produced independently from MapState.affected_clusters.

    Directly inspects the raw topology node definitions and active lease manifests.
    A cluster is ground-truth affected if:
    1. The zone node's assigned area matches the cluster's assigned area in the pack.
    2. An active task lease assigned to that cluster explicitly routes through the zone.
    """
    expected = set()
    node_data = pack.topology_doc.get("nodes", {}).get(zone, {})
    node_area = node_data.get("area")
    for cid, c_area in pack.topology_doc.get("clusters", {}).items():
        if node_area and (node_area == c_area or node_area in ("spine", "shared")):
            expected.add(cid)
    for l in leases:
        if zone in l.get("allowed_zones", []):
            expected.add(l["cluster_id"])
    return expected

def run_n5():
    out_dir = os.path.join("results", "final", "N5")
    plot_dir = os.path.join(out_dir, "plots")
    os.makedirs(plot_dir, exist_ok=True)
    setup_matplotlib_style()

    pack = Pack.load("hospital_sim6")
    topo = Topology(pack)
    mapstate = MapState(topo)
    clusters = sorted(list(topo.cluster_area.keys())) # ['east-wing', 'west-wing']

    all_zones = sorted(list(set(topo.nodes)))
    EVENTS_PER_SEED = 30

    event_types = ["corridor_blocked", "gate_closed", "hazard_spill", "isolation_declared", "high_congestion"]

    event_records = []
    summary_rows = []

    total_tp = 0
    total_fp = 0
    total_fn = 0
    total_tn = 0

    now = datetime.now(timezone.utc)

    for seed in range(1, 11):
        rng = np.random.default_rng(seed * 77 + 13)
        seed_tp, seed_fp, seed_fn, seed_tn = 0, 0, 0, 0

        # Live leases for this seed: each cluster's lease routes through 2 to 4 zones drawn from the whole map.
        live_leases = [
            {"cluster_id": cid, "allowed_zones": sorted(rng.choice(all_zones, size=int(rng.integers(2, 5)), replace=False).tolist())}
            for cid in clusters
        ]
        repo = MockRepo(live_leases)
        seed_zones = rng.choice(all_zones, size=EVENTS_PER_SEED, replace=True).tolist()
        seed_types = rng.choice(event_types, size=EVENTS_PER_SEED, replace=True).tolist()

        for event_idx, (zone, ev_type) in enumerate(zip(seed_zones, seed_types)):
            # Independent ground truth: derived directly from raw pack cluster areas and active leases
            ground_truth_affected = independent_ground_truth(zone, live_leases, pack)

            # System under test: MapState.affected_clusters
            system_predicted_clusters = mapstate.affected_clusters(zone, repo, now)
            informed_clusters = list(system_predicted_clusters)
            cross_wing_lease = any(zone in l["allowed_zones"] and topo.nodes[zone]["area"] not in (topo.cluster_area[l["cluster_id"]], "shared")
                                   for l in live_leases)

            for c in clusters:
                is_affected = (c in ground_truth_affected)
                is_informed = (c in informed_clusters)

                if is_affected and is_informed:
                    outcome = "TP"
                    seed_tp += 1
                elif (not is_affected) and is_informed:
                    outcome = "FP"
                    seed_fp += 1
                elif is_affected and (not is_informed):
                    outcome = "FN"
                    seed_fn += 1
                else:
                    outcome = "TN"
                    seed_tn += 1

                event_records.append({
                    "seed": seed,
                    "event_id": f"ev-{seed}-{event_idx+1}",
                    "zone": zone,
                    "event_type": ev_type,
                    "cluster": c,
                    "is_affected": is_affected,
                    "is_informed": is_informed,
                    "outcome": outcome,
                    "lease_crosses_wing_here": cross_wing_lease,
                    "source": "simulated"
                })

        total_tp += seed_tp
        total_fp += seed_fp
        total_fn += seed_fn
        total_tn += seed_tn

        recall = seed_tp / (seed_tp + seed_fn) if (seed_tp + seed_fn) > 0 else 1.0
        precision = seed_tp / (seed_tp + seed_fp) if (seed_tp + seed_fp) > 0 else 1.0

        summary_rows.append({
            "seed": seed,
            "events_run": len(seed_zones),
            "unique_zones": len(set(seed_zones)),
            "unique_events_zone_type": len(set(zip(seed_zones, seed_types))),
            "leases": json.dumps({l["cluster_id"]: l["allowed_zones"] for l in live_leases}),
            "clusters_evaluated": len(clusters),
            "tp": seed_tp,
            "fp": seed_fp,
            "fn": seed_fn,
            "tn": seed_tn,
            "recall_pct": round(recall * 100.0, 2),
            "precision_pct": round(precision * 100.0, 2),
            "source": "simulated"
        })

    # Save e6_sharing.csv
    df_events = pd.DataFrame(event_records)
    e6_path = os.path.join(out_dir, "e6_sharing.csv")
    df_events.to_csv(e6_path, index=False)

    # Save summary.csv
    df_sum = pd.DataFrame(summary_rows)
    sum_path = os.path.join(out_dir, "summary.csv")
    df_sum.to_csv(sum_path, index=False)

    overall_recall = total_tp / (total_tp + total_fn) * 100.0 if (total_tp + total_fn) else 100.0
    overall_precision = total_tp / (total_tp + total_fp) * 100.0 if (total_tp + total_fp) else 100.0
    n_events = int(df_events["event_id"].nunique())
    unique_events = int(df_events[["zone", "event_type"]].drop_duplicates().shape[0])
    unique_zones = int(df_events["zone"].nunique())
    unique_scenarios = int(df_sum.apply(lambda r: (r["leases"],), axis=1).nunique())
    cross_wing_events = int(df_events[df_events["lease_crosses_wing_here"]]["event_id"].nunique())

    # --- PLOTS ---
    # Plot 1: Confusion Matrix
    cm = np.array([[total_tp, total_fn], [total_fp, total_tn]])
    fig, ax = plt.subplots(figsize=(5.5, 4.8))
    cax = ax.matshow(cm, cmap="Blues", alpha=0.75)

    for i in range(2):
        for j in range(2):
            val = cm[i, j]
            label = f"{val}\n("
            if i == 0 and j == 0: label += f"TP: {val/max(1, total_tp+total_fn)*100:.1f}%)"
            elif i == 0 and j == 1: label += f"FN: {val/max(1, total_tp+total_fn)*100:.1f}%)"
            elif i == 1 and j == 0: label += f"FP: {val/max(1, total_fp+total_tn)*100:.1f}%)"
            else: label += f"TN: {val/max(1, total_fp+total_tn)*100:.1f}%)"
            ax.text(j, i, label, ha="center", va="center", color="black", fontsize=10, fontweight="bold")

    ax.set_xticks([0, 1])
    ax.set_yticks([0, 1])
    ax.set_xticklabels(["Informed", "Not Informed"])
    ax.set_yticklabels(["Affected", "Unaffected"])
    ax.set_title("N5: Selective Sharing Confusion Matrix (FR-11)", pad=15)
    fig.colorbar(cax, shrink=0.8)
    save_plots(fig, plot_dir, "confusion_matrix")

    # Plot 2: Precision & Recall by Event Type
    fig, ax = plt.subplots(figsize=(6.5, 4.2))
    type_metrics = []
    for et in event_types:
        sub = df_events[df_events["event_type"] == et]
        tp_t = len(sub[sub["outcome"] == "TP"])
        fp_t = len(sub[sub["outcome"] == "FP"])
        fn_t = len(sub[sub["outcome"] == "FN"])
        rec = tp_t / (tp_t + fn_t) if (tp_t + fn_t) > 0 else 1.0
        prec = tp_t / (tp_t + fp_t) if (tp_t + fp_t) > 0 else 1.0
        type_metrics.append((et.replace("_", " ").title(), rec * 100.0, prec * 100.0))

    x = np.arange(len(type_metrics))
    w = 0.35
    labels = [m[0] for m in type_metrics]
    recs = [m[1] for m in type_metrics]
    precs = [m[2] for m in type_metrics]

    ax.bar(x - w/2, recs, width=w, label="Recall (%)", color=COLOR_C1, edgecolor="black")
    ax.bar(x + w/2, precs, width=w, label="Precision (%)", color=COLOR_C2, edgecolor="black")

    ax.axhline(100.0, color=COLOR_PASS_BAR, linestyle="--", lw=1.5, label="PRD Pass Bar (100% Recall)")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=15, ha="right")
    ax.set_ylabel("Percentage (%)")
    ax.set_ylim(0, 115)
    ax.legend(loc="lower right")
    ax.grid(axis="y")
    ax.set_title(f"N5: Recall & precision by event type ({n_events} sampled events, 10 seeds)")
    save_plots(fig, plot_dir, "precision_recall")

    # Write env.json
    env = write_env_json(out_dir, experiment="N5", title="Selective sharing", prd="FR-11", source="simulated",
                         target="in-process cloud.mapstate.MapState on pack hospital_sim6, sampled events", model=None,
                         seeds=list(range(1, 11)))

    verdict_pass = total_fn == 0
    measured = (f"recall {overall_recall:.1f}% (TP {total_tp}, FN {total_fn}), precision {overall_precision:.1f}% (FP {total_fp}) "
                f"over {len(df_events)} cluster decisions for {n_events} sampled events; {unique_events} unique (zone, type) events, "
                f"{unique_zones}/{len(all_zones)} zones, {unique_scenarios} distinct lease layouts, {cross_wing_events} events in a zone a lease from the other wing routes through")
    notes = [
        "The seed's RNG now draws the events (zone and type) and the live leases; earlier versions ran one fixed list of 30 "
        "events ten times, so the ten seeds were copies.",
        "The expected set encodes the FR-11 rule (a cluster is affected if the zone is in its area or a shared area, or a live "
        "lease of it routes through the zone) straight from the pack's topology document, independently of MapState's code. "
        "This checks the implementation against the rule, not whether the rule tells the right people.",
        "Operator and requester notification are not evaluated (earlier versions reported a constant 100% for them).",
        "Verdict rule: PASS iff no affected cluster is missed (FN = 0); precision is reported.",
    ]
    write_readme(out_dir, exp_id="N5", title="Selective sharing",
                 claim="MapState tells every affected cluster about a map event (recall 100%) and few unaffected ones.",
                 pass_bar="Recall 100% (every affected cluster told) (FR-11); high precision (few unaffected).",
                 measured=measured, verdict="PASS" if verdict_pass else "FAIL", env=env, notes=notes)

    print(f"N5: recall {overall_recall:.1f}%, precision {overall_precision:.1f}%, {unique_events} unique events -> {'PASS' if verdict_pass else 'FAIL'}")

if __name__ == "__main__":
    run_n5()
