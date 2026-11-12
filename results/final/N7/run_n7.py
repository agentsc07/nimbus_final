"""N7: security and privacy audit (NFR-5), a static scan of this repository.

    python results/final/N7/run_n7.py

What it reads: IAM policy files under infra/ (scripts/audit_iam.py), tracked source for secret patterns
(audit_iam.secret_findings), evaluation/manifest.json and every file under evaluation/ and traces/ (manifest and PII
patterns, scripts/audit_data.py), and the WAN contracts in contracts/*.schema.json. It does not read git history or a
deployed account. Every count and the verdict come from `audit_checks`.
"""

import os
import json
import re
import subprocess
import pandas as pd
import matplotlib.pyplot as plt
from pathlib import Path
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))
sys.path.insert(0, os.getcwd())
from scripts.p4_shared import (
    COLOR_C1, COLOR_C2, COLOR_C3, COLOR_PASS_BAR,
    setup_matplotlib_style, save_plots, write_env_json, write_readme, GIT_COMMIT
)
import scripts.audit_iam as audit_iam
import scripts.audit_data as audit_data

# Inline-image signals in a JSON schema: a property named like image/photo/frame data, or binary/base64 content.
IMAGE_NAME = re.compile(r"(?i)(image|img|photo|picture|jpe?g|png|frame|camera|snapshot|base64|b64|bytes|blob|binary|data_?uri)")


def schema_inline_binary_fields(node, path="$"):
    """Every property in a JSON schema that could carry inline image or binary bytes."""
    found = []
    if isinstance(node, dict):
        if node.get("contentEncoding") or str(node.get("contentMediaType", "")).startswith("image/"):
            found.append(f"{path} (contentEncoding/contentMediaType)")
        if node.get("format") in ("binary", "byte"):
            found.append(f"{path} (format {node.get('format')})")
        for name, sub in (node.get("properties") or {}).items():
            if IMAGE_NAME.search(name):
                found.append(f"{path}.properties.{name}")
            found += schema_inline_binary_fields(sub, f"{path}.properties.{name}")
        for key, sub in node.items():
            if key != "properties" and isinstance(sub, (dict, list)):
                found += schema_inline_binary_fields(sub, f"{path}.{key}")
    elif isinstance(node, list):
        for i, sub in enumerate(node):
            found += schema_inline_binary_fields(sub, f"{path}[{i}]")
    return found

def run_n7():
    out_dir = os.path.join("results", "final", "N7")
    plot_dir = os.path.join(out_dir, "plots")
    os.makedirs(plot_dir, exist_ok=True)
    setup_matplotlib_style()

    # 1. IAM Audit
    iam_report_text, iam_passed = audit_iam.run()
    with open(os.path.join(out_dir, "audit_iam.txt"), "w", encoding="utf-8") as f:
        f.write(iam_report_text)

    # 2. Data Manifest & Synthetic Data Audit (cross-platform posix wrapper)
    root = Path.cwd()
    mpath = root / "evaluation" / "manifest.json"
    manifest_data = json.loads(mpath.read_text(encoding="utf-8"))
    
    # Copy manifest.json to results/final/N7/
    with open(os.path.join(out_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest_data, f, indent=2)

    data_problems = []
    listed = {d["path"].replace("\\", "/") for d in manifest_data["datasets"]}
    for d in manifest_data["datasets"]:
        if d.get("real_patient_data"):
            data_problems.append(f"{d['path']}: declares real patient data")
        if not (d.get("synthetic") is True or d.get("contains_personal_data") is False):
            data_problems.append(f"{d['path']}: must be synthetic")
        if not (root / d["path"]).exists():
            data_problems.append(f"{d['path']}: listed but not found")

    for base in ("evaluation", "traces"):
        bp = root / base
        if bp.exists():
            for f in bp.rglob("*"):
                rel = f.relative_to(root).as_posix()
                if f.is_file() and rel not in listed and f.name != "manifest.json":
                    data_problems.append(f"{rel}: not in manifest")

    # 3. Secret Scan across tracked source using canonical audit_iam rules
    secret_findings = audit_iam.secret_findings()

    secret_scan_report = [
        "# Nimbus Repository Secret Scan Report",
        f"- Working tree scanned at commit: {GIT_COMMIT} (tracked source only; git history is not scanned)",
        f"- Patterns Checked: AWS Access Key, AWS Secret Key, Private Key, GitHub/Slack Tokens, Hard-coded Passwords",
        f"- Total Vulnerabilities Found: {len(secret_findings)}",
        "",
        f"Status: {'CLEAN (No exposed secrets in code or configuration files)' if len(secret_findings) == 0 else 'FAIL (Exposed secrets detected)'}"
    ]
    with open(os.path.join(out_dir, "secret_scan_report.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(secret_scan_report) + "\n")

    # 4. PII: scripts/audit_data.py's patterns (e-mail, phone, national id, medical record number, date of birth) over
    # every dataset listed in the manifest. Only its PII findings are used here; the manifest check above is SEC-06.
    audit_data_problems = audit_data.audit(root)
    pii_findings = [p for p in audit_data_problems if "looks like it contains" in p]
    audit_data_other = [p for p in audit_data_problems if "looks like it contains" not in p]
    pii_clean = len(pii_findings) == 0

    # 5. WAN payload contracts: images may cross the WAN only by reference in OUTPUT_READY.
    esc_schema = json.loads(Path("contracts/escalation.schema.json").read_text(encoding="utf-8"))
    output_ready = next((b["then"]["properties"]["payload"] for b in esc_schema.get("allOf", [])
                         if b.get("if", {}).get("properties", {}).get("type", {}).get("const") == "OUTPUT_READY"), {})
    camera_wan_guard = (
        "OUTPUT_READY" in esc_schema.get("properties", {}).get("type", {}).get("enum", [])
        and output_ready.get("required") == ["result_ref"]
        and output_ready.get("properties", {}).get("result_ref", {}).get("type") == "string"
        and not schema_inline_binary_fields(output_ready)
    )
    inline_binary = {}
    for schema_path in sorted(Path("contracts").glob("*.schema.json")):
        hits = schema_inline_binary_fields(json.loads(schema_path.read_text(encoding="utf-8")))
        if hits:
            inline_binary[schema_path.as_posix()] = hits
    telemetry_clean = len(inline_binary) == 0

    # 5. Build dynamic summary table from real inspection results
    all_iam = audit_iam.iam_findings()
    bad_iam_actions = [f for f in all_iam if f["problem"].startswith("wildcard action") and not f.get("justified")]
    unjustified_iam = [f for f in all_iam if not f.get("justified")]

    audit_checks = [
        ("SEC-01", "IAM", "Zero wildcard '*' actions on data APIs", len(bad_iam_actions) == 0),
        ("SEC-02", "IAM", "Documented justifications for resource exceptions", len(unjustified_iam) == 0),
        ("SEC-03", "IAM", "Least-privilege Fargate task role policy", iam_passed),
        ("SEC-04", "Secrets", "Zero AWS access keys in repository", len([s for s in secret_findings if s["kind"] == "AWS access key id"]) == 0),
        ("SEC-05", "Secrets", "Zero secret patterns (keys, tokens, passwords) in tracked source", len(secret_findings) == 0),
        ("SEC-06", "Privacy", "100% synthetic dataset manifest declaration", len(data_problems) == 0),
        ("SEC-07", "Privacy", "Zero PII patterns (e-mail, phone, national id, MRN, date of birth) in manifest-listed datasets (scripts/audit_data.py)", pii_clean),
        ("SEC-08", "Privacy", "Traces declared free of personal patient data", all(d.get("contains_personal_data") is False for d in manifest_data["datasets"] if d["path"].startswith("traces/"))),
        ("SEC-09", "WAN Data", "OUTPUT_READY payload carries only a string result_ref (no inline image field)", camera_wan_guard),
        ("SEC-10", "WAN Data", "No contracts/*.schema.json declares an inline image/binary/base64 field", telemetry_clean),
    ]
    n_checks = len(audit_checks)
    n_passed = sum(1 for c in audit_checks if c[3])
    failed_ids = [c[0] for c in audit_checks if not c[3]]
    verdict_pass = n_passed == n_checks

    summary_rows = []
    for cid, cat, criteria, status in audit_checks:
        summary_rows.append({
            "check_id": cid,
            "category": cat,
            "pass_criteria": criteria,
            "audit_result": "PASS" if status else "FAIL",
            "source": "static_audit"
        })

    df_sum = pd.DataFrame(summary_rows)
    df_sum.to_csv(os.path.join(out_dir, "summary.csv"), index=False)

    with open(os.path.join(out_dir, "findings.json"), "w", encoding="utf-8") as f:
        json.dump({"iam_findings": all_iam, "secret_findings": secret_findings, "manifest_problems": data_problems,
                   "pii_findings": pii_findings, "inline_binary_schema_fields": inline_binary,
                   "audit_data_manifest_problems": audit_data_other}, f, indent=2, default=str)
        f.write("\n")

    # --- PLOT: Security & Privacy checklist, computed per category from audit_checks ---
    fig, ax = plt.subplots(figsize=(8.0, 5.0))
    cats = list(dict.fromkeys(c[1] for c in audit_checks))
    per_cat = [[c for c in audit_checks if c[1] == cat] for cat in cats]
    scores = [100.0 * sum(1 for c in cs if c[3]) / len(cs) for cs in per_cat]

    bars = ax.bar(cats, scores, color=[COLOR_C1 if sc == 100.0 else COLOR_PASS_BAR for sc in scores], edgecolor="black", width=0.45)
    for b, cs in zip(bars, per_cat):
        ok = sum(1 for c in cs if c[3])
        label = f"{ok}/{len(cs)} pass" + ("" if ok == len(cs) else "\nFAIL: " + ", ".join(c[0] for c in cs if not c[3]))
        ax.text(b.get_x() + b.get_width()/2., max(b.get_height(), 0) + 3, label, ha="center", va="bottom", fontsize=9, fontweight="bold")

    ax.axhline(100.0, color=COLOR_PASS_BAR, linestyle="--", lw=1.5, label="PRD Pass Bar (every check passes)")
    ax.set_ylim(0, 125)
    ax.set_ylabel("Checks passed (%)")
    ax.set_title(f"N7: Static security & privacy audit, {n_passed}/{n_checks} checks pass (NFR-5)")
    ax.legend(loc="upper right")
    ax.grid(axis="y")
    save_plots(fig, plot_dir, "security_checklist")

    # Write env.json
    env = write_env_json(out_dir, experiment="N7", title="Security and privacy audit", prd="NFR-5",
                         source="static_audit", target="static scan of this repository's working tree; no git history, no deployed account",
                         model=None, seeds=None)

    measured = (f"{n_passed}/{n_checks} static checks passed"
                + (f" (failed: {', '.join(failed_ids)})" if failed_ids else "")
                + f"; {len(unjustified_iam)} unjustified IAM wildcards ({len(all_iam)} wildcard statements); "
                f"{len(secret_findings)} secret-pattern hits in tracked source; {len(data_problems)} manifest problems; "
                f"{len(pii_findings)} PII-pattern hits; {sum(len(v) for v in inline_binary.values())} inline image/binary schema fields")
    notes = [
        "Source is `static_audit`: a scan of the files in this checkout. It does not inspect git history, the deployed IAM "
        "roles, or traffic on the wire, so it shows what the repository declares, not what a running system sends.",
        "SEC-07 uses scripts/audit_data.py's PII patterns (e-mail, phone, national id, medical record number, date of birth) "
        "over every dataset the manifest lists (not only traces/). SEC-06 checks the manifest itself, comparing POSIX paths.",
        "SEC-10 replaces an earlier check that string-matched contracts/topics.md for the word 'image' (it failed on a "
        "documented upload content type). It now walks every contracts/*.schema.json for properties named like image/photo/"
        "frame/base64/bytes or declaring contentEncoding, contentMediaType image/* or format binary/byte.",
        "Limitation of SEC-09/SEC-10: the escalation schema's payload objects do not set additionalProperties to false, so "
        "the schemas alone do not forbid an extra inline-image key in, say, an UNEXPECTED_EVENT payload; runtime enforcement "
        "is not audited here.",
        "Verdict rule: PASS iff every check in summary.csv passes; findings.json lists what each check found.",
    ]
    if len(audit_data_other) != len(data_problems):
        notes.append(f"scripts/audit_data.py's own manifest check reported {len(audit_data_other)} problem(s) on this host against "
                     f"SEC-06's {len(data_problems)} (listed in findings.json as audit_data_manifest_problems). On Windows its "
                     "'not listed in the manifest' check compares backslash paths with the manifest's forward-slash paths.")
    write_readme(out_dir, exp_id="N7", title="Security and privacy audit",
                 claim="The repository declares least-privilege IAM, holds no secrets in tracked source, uses only synthetic data, and its WAN contracts carry images only by reference in OUTPUT_READY.",
                 pass_bar="No wildcard IAM on data; no secrets in code; 100% synthetic data; images only inside OUTPUT_READY (NFR-5).",
                 measured=measured, verdict="PASS" if verdict_pass else "FAIL", env=env, notes=notes)

    print(f"N7: {n_passed}/{n_checks} checks passed -> {'PASS' if verdict_pass else 'FAIL'}")

if __name__ == "__main__":
    run_n7()
