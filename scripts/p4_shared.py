"""Shared helpers for the network and infrastructure runners (results/final/N<n>/run_n<n>.py).

Provenance is computed at run time, never typed in: the git commit (with `-dirty` when the working tree has
uncommitted changes), the command line, the seeds and the run start/finish times. AWS account and Bedrock model are
`null` unless a runner says it really used them (none of N2 to N10 does). `write_readme` writes the fixed README
format of docs/RESULTS_GUIDE.md, which `experiments/cloud/report.py` parses into results/final/RESULTS.md.
"""

import os
import sys
import json
import time
import platform
import subprocess
from pathlib import Path

import psutil
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]


def utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def git_commit() -> str:
    """`git rev-parse HEAD`, plus `-dirty` when tracked or untracked files differ from it; 'unknown' without git."""
    try:
        sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True,
                                      stderr=subprocess.DEVNULL).strip()
        status = subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True,
                                         stderr=subprocess.DEVNULL).strip()
        return sha + ("-dirty" if status else "")
    except Exception:
        return "unknown"


def command_line() -> str:
    """The command that produced this run, with the script path relative to the repository root."""
    script = Path(sys.argv[0]).resolve() if sys.argv and sys.argv[0] else None
    if script is not None and ROOT in script.parents:
        name = script.relative_to(ROOT).as_posix()
    else:
        name = sys.argv[0] if sys.argv else "?"
    return " ".join(["python", name] + sys.argv[1:])


GIT_COMMIT = git_commit()      # computed once per run (kept as a name for the runners' imports)
RUN_STARTED_UTC = utc_now()

# Color palette: C1 blue, C2 orange, C3 grey
COLOR_C1 = "#1f77b4"
COLOR_C2 = "#ff7f0e"
COLOR_C3 = "#7f7f7f"
COLOR_PASS_BAR = "#d62728"


def get_env_dict(**fields):
    """env.json contents. Pass experiment, title, prd, source, target, model, seeds (and anything else) as fields.
    aws_region / aws_account_id / bedrock_model_id stay null unless the runner passes values it really used."""
    env = {
        "experiment": None,
        "title": None,
        "prd": None,
        "source": None,
        "target": None,
        "model": None,
        "seeds": None,
        "git_commit": GIT_COMMIT,
        "command": command_line(),
        "started_utc": RUN_STARTED_UTC,
        "finished_utc": utc_now(),
        "host": platform.node(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "cpu_count_logical": os.cpu_count(),
        "memory_total_gb": round(psutil.virtual_memory().total / (1024**3), 2),
        "python_version": platform.python_version(),
        "aws_region": None,
        "aws_account_id": None,
        "bedrock_model_id": None,
    }
    env.update(fields)
    return env


def write_env_json(output_dir: str, **fields):
    """Write env.json and return its contents (pass the result to write_readme)."""
    os.makedirs(output_dir, exist_ok=True)
    env = get_env_dict(**fields)
    with open(os.path.join(output_dir, "env.json"), "w", encoding="utf-8") as f:
        json.dump(env, f, indent=2)
        f.write("\n")
    return env


def setup_matplotlib_style():
    plt.rcParams.update({
        "font.family": "sans-serif",
        "font.sans-serif": ["DejaVu Sans", "Arial", "Helvetica"],
        "axes.edgecolor": "#333333",
        "axes.linewidth": 0.8,
        "grid.color": "#cccccc",
        "grid.linestyle": ":",
        "grid.linewidth": 0.6,
        "grid.alpha": 0.7,
        "legend.frameon": True,
        "legend.facecolor": "#ffffff",
        "legend.edgecolor": "#cccccc",
        "figure.titlesize": 12,
        "axes.titlesize": 11,
        "axes.labelsize": 10,
        "xtick.labelsize": 9,
        "ytick.labelsize": 9,
        "legend.fontsize": 9,
        "figure.autolayout": True,
        "svg.hashsalt": "nimbus-p4",     # stable SVG ids, so a seeded rerun gives the same files
    })


def save_plots(fig, plot_dir: str, base_name: str):
    os.makedirs(plot_dir, exist_ok=True)
    png_path = os.path.join(plot_dir, f"{base_name}.png")
    svg_path = os.path.join(plot_dir, f"{base_name}.svg")
    fig.savefig(png_path, dpi=300, bbox_inches="tight")
    fig.savefig(svg_path, bbox_inches="tight", metadata={"Date": None})
    plt.close(fig)
    return png_path, svg_path


def write_readme(output_dir: str, *, exp_id: str, title: str, claim: str, pass_bar: str, measured: str,
                 verdict: str, env: dict, plots=None, notes=None):
    """README.md in the docs/RESULTS_GUIDE.md format (the fields experiments/cloud/report.py reads).

    `env` is the dict write_env_json returned: source, target, model, command, commit and run times come from it,
    so the README and env.json cannot disagree."""
    os.makedirs(output_dir, exist_ok=True)
    if plots is None:
        plot_dir = Path(output_dir) / "plots"
        plots = sorted(p.stem for p in plot_dir.glob("*.png")) if plot_dir.is_dir() else []
    source = env.get("source") or "unknown"
    detail = ", ".join(x for x in (env.get("target"), f"model {env['model']}" if env.get("model") else None) if x)
    lines = [f"# {exp_id}: {title}", "",
             f"- **Claim:** {claim.strip()}",
             f"- **PRD pass bar:** {pass_bar.strip()}",
             f"- **Measured:** {measured.strip()}",
             f"- **Verdict:** {verdict.strip()}",
             f"- **Source of numbers:** {source}" + (f" ({detail})" if detail else ""),
             f"- **Command:** `{env.get('command') or command_line()}`",
             f"- **Commit:** {env.get('git_commit') or GIT_COMMIT}, run {env.get('started_utc')} to {env.get('finished_utc')}",
             ""]
    if plots:
        lines += ["## Plots", ""] + [f"![{p}](plots/{p}.png)" for p in plots] + [""]
    if notes:
        lines += ["## Notes", ""] + [f"- {n.strip()}" for n in notes] + [""]
    path = os.path.join(output_dir, "README.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return path
