"""Collect every experiment folder in results/final/ into one table: results/final/RESULTS.md.

Reads each folder's README.md (claim, pass bar, measured, verdict) and env.json (source, target, model, commit), so the
table is always rebuilt from what the experiments wrote, never typed by hand.

    python experiments/cloud/report.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lib  # noqa: E402

GROUP_ORDER = {"C": 0, "R": 1, "N": 2, "T": 3, "E": 4}
GROUPS = [("C", "Cloud (C1 to C9)", 9), ("R", "Robot and edge (R1 to R10)", 10),
          ("N", "Network and infrastructure (N1 to N10)", 10), ("T", "Scenario tests (T1 to T8, experiment E3)", 8)]
ORDER = ["C1", "C1_deployed", "C1_standin", "C2", "C2_standin", "C3", "C3_standin", "C4", "C5", "C6", "C6_local",
         "C7", "C7_local", "C8", "C8_local", "C9", "C9_standin"]
# PRD requirement(s) each experiment tests (from the plan; used when a folder's env.json does not say).
PRD = {"C1": "FR-13", "C2": "FR-17", "C3": "FR-19", "C4": "FR-15", "C5": "FR-14, T8", "C6": "FR-16, T5", "C7": "FR-18",
       "C8": "NFR-1 (cloud)", "C9": "NFR-4",
       "R1": "FR-1", "R2": "FR-2", "R3": "FR-2, FR-5", "R4": "E1, NFR-1, FR-3", "R5": "FR-4", "R6": "FR-5", "R7": "FR-6",
       "R8": "FR-7", "R9": "FR-10, FR-12, NFR-2", "R10": "FR-9",
       "N1": "E4 input", "N2": "E4", "N3": "FR-6, NFR-2", "N4": "FR-8", "N5": "FR-11", "N6": "FR-20, NFR-6", "N7": "NFR-5",
       "N8": "NFR-3", "N9": "NFR-4", "N10": "FR-21, FR-22",
       "T1": "E3", "T2": "E3", "T3": "E3", "T4": "E3", "T5": "E3", "T6": "E3", "T7": "E3", "T8": "E3"}
# Results that live outside results/final/ (the one-touch scenario scripts write there).
ELSEWHERE = {"T1": "T1_results", "T3": "T3_results", "T6": "T6_results", "T8": "T8_results"}
SOURCE_NOTE = ("Source: `real_bedrock` = Amazon Bedrock Nova Lite (deployed cloud or our own local server); "
               "`real_slm` = a real edge model; `mock_llm` = the rule-based stand-in model (protocol and code behaviour, "
               "not model quality); `measured` = no model involved, or a physical/simulated measurement; "
               "`modelled` / `simulated` = computed from a model or a simulation rather than the running system.")


def field(text: str, name: str) -> str:
    m = re.search(rf"\*\*{re.escape(name)}:\*\* (.+)", text)
    return m.group(1).strip() if m else ""


def cell(v: str) -> str:
    return (v or "").replace("|", "/").replace("\n", " ").strip()


def short_commit(v: str) -> str:
    m = re.match(r"([0-9a-f]{7,40})(-dirty)?", v or "")
    return (m.group(1)[:7] + (m.group(2) or "")) if m else cell(v)[:24]


def plots(d: Path) -> str:
    pngs = sorted(p.name for p in (d / "plots").glob("*.png")) if (d / "plots").is_dir() else []
    return ", ".join(f"[{Path(p).stem}]({d.name}/plots/{p})" for p in pngs) or "none"


def row_for(d: Path) -> dict:
    text = (d / "README.md").read_text(encoding="utf-8")
    env = json.loads((d / "env.json").read_text()) if (d / "env.json").exists() else {}
    exp = d.name.split("_")[0]
    source = env.get("source") or re.split(r"[ (]", field(text, "Source of numbers") or " ")[0]
    return {"run": f"[{d.name}]({d.name}/README.md)", "prd": env.get("prd") or PRD.get(exp, ""),
            "verdict": field(text, "Verdict"), "measured": field(text, "Measured"), "source": source,
            "plots": plots(d), "commit": short_commit(env.get("git_commit") or field(text, "Commit")),
            "pass_bar": field(text, "PRD pass bar"), "name": d.name}


def key(d: Path):
    num = re.match(r"([A-Z])(\d+)", d.name)
    return (GROUP_ORDER.get(d.name[0], 9), int(num.group(2)) if num else 99,
            ORDER.index(d.name) if d.name in ORDER else 99, d.name)


def main() -> int:
    root = lib.RESULTS
    dirs = sorted((d for d in root.iterdir() if d.is_dir() and re.match(r"[A-Z]\d+", d.name)), key=key)
    by_exp: dict[str, list[Path]] = {}
    for d in dirs:
        by_exp.setdefault(d.name.split("_")[0], []).append(d)
    head = "| Run | PRD | Verdict | Measured | Source | Plots | Commit |"
    lines = ["# Experiment results", "",
             "Built by `python experiments/cloud/report.py` from each folder's README.md and env.json, never typed by "
             "hand. Every row links to a folder with the raw records, summary, plots and environment. How to add a row: "
             "[docs/RESULTS_GUIDE.md](../../docs/RESULTS_GUIDE.md). Rows marked *to be filled* have no result folder "
             "with a README yet.", "", SOURCE_NOTE, ""]
    bars = []
    for g, title, n in GROUPS:
        lines += [f"## {title}", "", head, "| --- | --- | --- | --- | --- | --- | --- |"]
        for i in range(1, n + 1):
            exp = f"{g}{i}"
            found = [d for d in by_exp.get(exp, []) if (d / "README.md").exists()]
            for d in found:
                r = row_for(d)
                lines.append(f"| {r['run']} | {r['prd']} | {cell(r['verdict'])} | {cell(r['measured'])} | "
                             f"{cell(r['source'])} | {r['plots']} | {r['commit']} |")
                bars.append((r["name"], r["pass_bar"]))
            if not found:
                where = [d for d in by_exp.get(exp, [])] or ([Path(ELSEWHERE[exp])] if exp in ELSEWHERE and
                                                            (root.parents[1] / ELSEWHERE[exp]).is_dir() else [])
                note = "to be filled"
                if where:
                    rel = f"{where[0].name}/" if where[0].parent == root else f"../../{where[0]}/"
                    note = f"to be filled (results in progress: [{rel}]({rel}))"
                lines.append(f"| {exp} | {PRD.get(exp, '')} | | {note} | | | |")
        lines.append("")
    lines += ["## Pass bars", "", "| Run | PRD pass bar |", "| --- | --- |"]
    lines += [f"| {name} | {cell(bar)} |" for name, bar in bars]
    (root / "RESULTS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {root / 'RESULTS.md'} ({len(bars)} result folders)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
