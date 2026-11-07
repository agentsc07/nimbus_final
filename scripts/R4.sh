#!/usr/bin/env bash
# R4 — Edge SLM Benchmarking preflight and launcher.
#
# This script intentionally refuses to substitute mocks or silently benchmark a
# different model. It invokes only the repository's E1 benchmark after its
# workload/model-selection preconditions are met.
set -euo pipefail

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
BENCHMARK="$ROOT/edge/benchmarks/e1_benchmark.py"
ENGINE="$ROOT/edge/slm/engine.py"
OUT="$ROOT/results/final/R4"
MODE="${1:-}"
MODELS=("qwen2.5:0.5b" "qwen2.5:1.5b" "qwen2.5:3b")

usage() {
  cat <<'EOF'
Usage:
  ./scripts/R4.sh --smoke
  ./scripts/R4.sh --full

--smoke requires 5 labelled situations x 1 repetition x 3 real Ollama models.
--full  requires 5 labelled situations x 10 repetitions x 3 real Ollama models.
EOF
}

[[ "$MODE" == "--smoke" || "$MODE" == "--full" ]] || { usage >&2; exit 64; }
[[ -f "$BENCHMARK" && -f "$ENGINE" ]] || { echo "[R4] ERROR: E1 benchmark or SLM engine is missing." >&2; exit 1; }

echo "[R4] mode=$MODE"
echo "[R4] benchmark=$BENCHMARK"
echo "[R4] hardware: $(uname -srm)"
if command -v nvidia-smi >/dev/null 2>&1; then
  nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader || true
fi
if command -v free >/dev/null 2>&1; then
  free -m | awk 'NR==2 { printf "[R4] system_memory_mb=%s\n", $2 }'
fi

if ! command -v ollama >/dev/null 2>&1; then
  echo "[R4] BLOCKED: Ollama is not installed. Install Ollama, then run:" >&2
  printf '  ollama pull %s\n' "${MODELS[@]}" >&2
  exit 2
fi

if ! ollama list >/tmp/nimbus-r4-ollama-list.$$ 2>/dev/null; then
  echo "[R4] BLOCKED: Ollama is installed but its local server is unavailable." >&2
  echo "[R4] Start it with: ollama serve" >&2
  rm -f "/tmp/nimbus-r4-ollama-list.$$"
  exit 2
fi

missing=0
for model in "${MODELS[@]}"; do
  if ! awk 'NR > 1 { print $1 }' "/tmp/nimbus-r4-ollama-list.$$" | grep -Fxq "$model"; then
    echo "[R4] BLOCKED: required model is not installed: $model" >&2
    echo "[R4] Obtain it with: ollama pull $model" >&2
    missing=1
  else
    echo "[R4] model available: $model"
    # `ollama show --verbose` is recorded verbatim at execution time by the
    # benchmark's own output; it exposes the actual Ollama digest/quantisation
    # when that version of Ollama supports it.
    ollama show --verbose "$model" 2>/dev/null | sed -n '1,80p' || true
  fi
done
rm -f "/tmp/nimbus-r4-ollama-list.$$"
(( missing == 0 )) || exit 2

# E1 currently supplies five labelled situations. The requested R4 scope is
# therefore the complete existing E1 prompt set: 5x1 per model for smoke and
# 5x10 per model for full. This script uses E1's prompt list and helpers, but
# creates EdgeSLMEngine in explicit real-Ollama mode: E1's own CLI runs four
# trials and its mode=auto path would rewrite the requested model to 1.5B.
PROMPT_COUNT="$(grep -c '"id": "SC-' "$BENCHMARK" || true)"
[[ "$PROMPT_COUNT" == "5" ]] || { echo "[R4] BLOCKED: expected E1's current 5 labelled prompts; found $PROMPT_COUNT." >&2; exit 2; }
if [[ "$MODE" == "--smoke" ]]; then REPS=1; else REPS=10; fi

mkdir -p "$OUT"
echo "[R4] real Ollama benchmark: $PROMPT_COUNT situations x $REPS repetitions x ${#MODELS[@]} models"

python3 - "$ROOT" "$OUT" "$REPS" "$MODE" "${MODELS[@]}" <<'PY'
import csv
import json
import platform
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

root, out, repetitions, mode, *models = sys.argv[1:]
root, out, repetitions = Path(root), Path(out), int(repetitions)
sys.path.insert(0, str(root))
from edge.benchmarks.e1_benchmark import BENCHMARK_PROMPTS, compute_p95, estimate_tokens
from edge.slm.engine import ALLOWED_TACTICAL_ACTIONS, EdgeSLMEngine

def gpu_memory_mb():
    try:
        text = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            text=True, stderr=subprocess.DEVNULL,
        )
        values = [int(line.strip()) for line in text.splitlines() if line.strip().isdigit()]
        return max(values) if values else None
    except Exception:
        return None

def model_metadata(model):
    try:
        text = subprocess.check_output(["ollama", "show", "--verbose", model], text=True, stderr=subprocess.STDOUT)
    except Exception as exc:
        return {"show_error": str(exc)}
    metadata = {"show": text}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] == "quantization":
            metadata["quantization"] = parts[-1]
        elif len(parts) >= 2 and parts[0] == "parameters":
            metadata["parameters"] = parts[-1]
    return metadata

fieldnames = ["model", "scenario", "run", "latency_s", "valid_json", "allowed_action", "output_tokens", "tokens_per_second", "memory_mb", "error"]
rows, summaries, metadata = [], [], {}
for model in models:
    print(f"[R4] model={model}: cold start, then {len(BENCHMARK_PROMPTS) * repetitions} sequential decisions", flush=True)
    # Explicit mode is required: no auto-mode model substitution and no mocks.
    engine = EdgeSLMEngine(model_name=model, mode="ollama")
    if engine.mode != "ollama" or engine.model_name != model:
        raise RuntimeError(f"real-Ollama model selection failed for {model}: mode={engine.mode}, model={engine.model_name}")
    cold = engine.cold_start_latency_s
    metadata[model] = model_metadata(model)
    model_rows = []
    for run in range(1, repetitions + 1):
        for scenario in BENCHMARK_PROMPTS:
            decision, decided_by, latency_ms = engine.evaluate_decision(dict(scenario["context"]))
            latency_s = float(latency_ms) / 1000.0
            valid = isinstance(decision, dict) and bool(decision.get("action"))
            allowed = valid and decision.get("action") in ALLOWED_TACTICAL_ACTIONS
            tokens = estimate_tokens(decision)
            # SC-05 deliberately exercises the engine's pre-inference lease
            # invariant; it is a required deterministic safety decision, not
            # an inference failure and not a model throughput sample.
            invariant = float(scenario["context"].get("time_remaining_sec", 999.0)) <= 30.0
            error = "" if decided_by == "SLM" else ("deterministic_safety_rule" if invariant else "engine_rule_fallback")
            throughput = (tokens / latency_s) if latency_s > 0 and decided_by == "SLM" else None
            row = {
                "model": model, "scenario": scenario["id"], "run": run,
                "latency_s": f"{latency_s:.6f}", "valid_json": str(valid).lower(),
                "allowed_action": str(allowed).lower(), "output_tokens": tokens,
                "tokens_per_second": "" if throughput is None else f"{throughput:.3f}",
                "memory_mb": gpu_memory_mb(), "error": error,
            }
            rows.append(row); model_rows.append(row)
    inference_rows = [row for row in model_rows if not row["error"]]
    latencies = [float(row["latency_s"]) for row in inference_rows]
    tokens = [int(row["output_tokens"]) for row in inference_rows]
    valid_rate = 100.0 * sum(row["valid_json"] == "true" for row in model_rows) / len(model_rows)
    allowed_rate = 100.0 * sum(row["allowed_action"] == "true" for row in model_rows) / len(model_rows)
    peak_memory = max((int(row["memory_mb"]) for row in model_rows if row["memory_mb"] not in (None, "")), default=None)
    token_rate = sum(tokens) / sum(latencies) if sum(latencies) else 0.0
    fallback_count = sum(row["error"] == "engine_rule_fallback" for row in model_rows)
    passed = compute_p95(latencies) <= 10.0 and max(tokens) <= 150 and valid_rate == 100.0 and allowed_rate == 100.0 and fallback_count == 0
    summaries.append({
        "model": model, "decisions": len(model_rows), "p50_warm_latency_s": f"{statistics.median(latencies):.6f}",
        "p95_warm_latency_s": f"{compute_p95(latencies):.6f}", "cold_start_latency_s": cold,
        "valid_json_pct": f"{valid_rate:.1f}", "allowed_action_pct": f"{allowed_rate:.1f}",
        "tokens_per_second": f"{token_rate:.3f}", "peak_memory_mb": peak_memory,
        "slm_decisions": len(inference_rows), "rule_fallbacks": fallback_count, "pass": str(passed).lower(),
    })

with (out / "results.csv").open("w", newline="") as handle:
    writer = csv.DictWriter(handle, fieldnames=fieldnames); writer.writeheader(); writer.writerows(rows)
summary_fields = list(summaries[0])
with (out / "summary.csv").open("w", newline="") as handle:
    writer = csv.DictWriter(handle, fieldnames=summary_fields); writer.writeheader(); writer.writerows(summaries)
env = {
    "experiment": "R4", "mode": mode, "source": "measured", "backend": "Ollama", "engine_mode": "ollama",
    "situations": len(BENCHMARK_PROMPTS), "repetitions": repetitions, "max_output_tokens": 150,
    "temperature": 0.2, "host": {"platform": platform.platform(), "processor": platform.processor()},
    "models": metadata, "created_utc": datetime.now(timezone.utc).isoformat(),
}
(out / "env.json").write_text(json.dumps(env, indent=2) + "\n")
lines = ["# R4: Edge SLM Benchmarking", "", f"- **Workload:** {len(BENCHMARK_PROMPTS)} existing E1 labelled situations × {repetitions} repetitions × {len(models)} models.", "- **Backend:** actual local Ollama, sequential execution; no mock mode.", "- **Generation policy:** existing `EdgeSLMEngine` fixed settings: `num_predict=150`, `temperature=0.2`.", "- **Scope limitation:** E1 currently has five labelled situations, not forty.", "- **Metric limitation:** the engine returns a validated decision or rule fallback, so `valid_json` measures the returned normalized decision; raw malformed-model-output rate is not exposed. Output tokens use E1's serialized-decision estimate, not Ollama generation telemetry.", "", "## Summary", "", "| Model | p50 warm s | p95 warm s | Cold s | JSON % | Allowed % | Tokens/s (estimated) | Peak GPU MB | Rule fallbacks | PASS |", "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |"]
for row in summaries:
    lines.append(f"| {row['model']} | {row['p50_warm_latency_s']} | {row['p95_warm_latency_s']} | {row['cold_start_latency_s']} | {row['valid_json_pct']} | {row['allowed_action_pct']} | {row['tokens_per_second']} | {row['peak_memory_mb']} | {row['rule_fallbacks']} | {row['pass']} |")
(out / "README.md").write_text("\n".join(lines) + "\n")
try:
    import matplotlib.pyplot as plt
    plots = out / "plots"; plots.mkdir(exist_ok=True)
    labels = [row["model"] for row in summaries]
    fig, ax = plt.subplots(figsize=(7, 4)); ax.bar(labels, [float(row["p95_warm_latency_s"]) for row in summaries]); ax.set_ylabel("p95 warm latency (s)"); ax.set_title("R4 real-Ollama latency"); fig.tight_layout(); fig.savefig(plots / "p95_latency.png", dpi=150); plt.close(fig)
    fig, ax = plt.subplots(figsize=(7, 4)); ax.bar(labels, [float(row["valid_json_pct"]) for row in summaries]); ax.set_ylim(0, 100); ax.set_ylabel("valid normalized decision (%)"); ax.set_title("R4 decision validity"); fig.tight_layout(); fig.savefig(plots / "validity.png", dpi=150); plt.close(fig)
except Exception as exc:
    with (out / "README.md").open("a") as handle:
        handle.write(f"\nPlots unavailable: {exc}\n")
print(f"[R4] wrote {out}/results.csv, summary.csv, env.json, README.md", flush=True)
PY
