"""Regression tests for red-team issue #20 (NFR-5): the Terraform deployment ran a mutable `:latest` image and let
the service container send anything anywhere.

Static checks on infra/terraform/*.tf and scripts/build_push.sh, so they run without the terraform binary or AWS
credentials. `terraform validate` is run separately (see the PR).
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TF_DIR = ROOT / "infra" / "terraform"
BUILD_PUSH = ROOT / "scripts" / "build_push.sh"

DIGEST = "0123456789abcdef" * 4  # 64 hex characters
REPO = "123456789012.dkr.ecr.ap-south-1.amazonaws.com/nimbus-app"


def _code(text: str) -> str:
    """HCL without comments, so a `:latest` or `0.0.0.0/0` in a comment does not count."""
    kept = []
    for line in text.splitlines():
        if line.lstrip().startswith(("#", "//")):
            continue
        kept.append(re.sub(r'\s+#[^"\n]*$', "", line))
    return "\n".join(kept)


def _terraform() -> str:
    files = sorted(TF_DIR.glob("*.tf"))
    assert files, f"no .tf files in {TF_DIR}"
    return "\n".join(_code(path.read_text(encoding="utf-8")) for path in files)


def _body(text: str, open_brace: int) -> str:
    depth = 0
    for index in range(open_brace, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[open_brace + 1 : index]
    raise AssertionError("unbalanced braces in Terraform source")


def _blocks(text: str, header: str) -> list[str]:
    """Bodies of every block whose header matches the regex `header`."""
    return [_body(text, match.end() - 1) for match in re.finditer(header + r"\s*\{", text)]


def _block(text: str, header: str) -> str:
    found = _blocks(text, header)
    assert len(found) == 1, f"expected exactly one block matching {header!r}, found {len(found)}"
    return found[0]


def _attr(block: str, name: str) -> str:
    match = re.search(rf"^\s*{name}\s*=\s*(.+?)\s*$", block, re.M)
    assert match, f"attribute {name} missing in block:\n{block}"
    return match.group(1)


# --- 1. The image ECS runs is pinned ------------------------------------------------------------------------------


def test_issue20_ecr_repository_tags_are_immutable():
    repo = _block(_terraform(), r'resource\s+"aws_ecr_repository"\s+"app"')
    assert _attr(repo, "image_tag_mutability") == '"IMMUTABLE"'


def test_issue20_task_definition_runs_an_image_pinned_by_digest():
    code = _terraform()
    assert not re.search(r':latest"', code), "no image reference may end in the moving :latest tag"

    task = _block(code, r'resource\s+"aws_ecs_task_definition"\s+"app"')
    assert re.search(r"\bimage\s*=\s*local\.app_image\b", task)

    definitions = [
        found
        for body in _blocks(code, r"\blocals")
        if (found := re.search(r"^\s*app_image\s*=(.*?)(?=^\s*\w+\s*=|\Z)", body, re.M | re.S))
    ]
    assert len(definitions) == 1, "local.app_image must be defined exactly once"
    expression = definitions[0].group(1)
    assert re.search(r"@\$\{data\.aws_ecr_image\.app(\[0\])?\.image_digest\}", expression), (
        "the ECR fallback must reference the image by its digest"
    )

    precondition = _block(task, r"\bprecondition")
    assert "local.app_image" in _attr(precondition, "condition"), (
        "plan must stop with a clear error when no image was chosen, instead of deploying an empty image"
    )


def test_issue20_app_image_variable_accepts_only_a_digest_reference():
    variable = _block(_terraform(), r'variable\s+"app_image"')
    validation = _block(variable, r"\bvalidation")
    condition = _attr(validation, "condition")
    assert 'var.app_image == ""' in condition, "empty must stay allowed: it means use app_image_tag"

    pattern = re.search(r'regex\(\s*"([^"]+)"', condition)
    assert pattern, "app_image validation must check the reference with regex()"
    pinned = re.compile(pattern.group(1).replace("\\\\", "\\"))
    assert pinned.search(f"{REPO}@sha256:{DIGEST}")
    assert not pinned.search(f"{REPO}:latest")
    assert not pinned.search(f"{REPO}:3f2a1b9c")
    assert not pinned.search(f"{REPO}@sha256:{DIGEST[:-1]}")


def test_issue20_app_image_tag_variable_refuses_latest():
    variable = _block(_terraform(), r'variable\s+"app_image_tag"')
    condition = _attr(_block(variable, r"\bvalidation"), "condition")
    assert re.search(r'var\.app_image_tag\s*!=\s*"latest"', condition)


def test_issue20_build_push_tags_with_the_commit_and_refuses_latest():
    script = BUILD_PUSH.read_text(encoding="utf-8")
    assert "${1:-latest}" not in script, "the default tag must not be latest"
    assert "git rev-parse" in script, "the default tag must come from the commit"
    assert re.search(r'"\$TAG"\s*==?\s*"latest"', script), "pushing latest must be refused explicitly"


# --- 2. What the container can reach ------------------------------------------------------------------------------


def test_issue20_app_security_group_allows_only_https_out():
    group = _block(_terraform(), r'resource\s+"aws_security_group"\s+"app"')
    rules = _blocks(group, r"\begress")
    assert rules, "the app security group needs an explicit egress rule"
    for rule in rules:
        assert _attr(rule, "protocol") == '"tcp"'
        assert _attr(rule, "from_port") == "443"
        assert _attr(rule, "to_port") == "443"


def test_issue20_no_security_group_opens_every_protocol_to_the_internet():
    code = _terraform()
    for group in _blocks(code, r'resource\s+"aws_security_group"\s+"\w+"'):
        for rule in _blocks(group, r"\begress"):
            if "0.0.0.0/0" in rule or "::/0" in rule:
                assert _attr(rule, "protocol") != '"-1"', f"all-protocol egress to the internet:\n{rule}"


def test_issue20_s3_and_dynamodb_use_gateway_endpoints():
    services = set()
    for endpoint in _blocks(_terraform(), r'resource\s+"aws_vpc_endpoint"\s+"\w+"'):
        if _attr(endpoint, "vpc_endpoint_type") == '"Gateway"':
            name = re.search(r'service_name\s*=\s*"com\.amazonaws\.\$\{var\.aws_region\}\.(\w+)"', endpoint)
            assert name, f"unexpected service_name in:\n{endpoint}"
            services.add(name.group(1))
    assert {"s3", "dynamodb"} <= services
