"""Red-team issues #14, #15, #16 (P4): task-data auth, /health, and the security matrix vs enforced rules.

#14  GET /tasks/{id} (and /map.json, which lists every task) need a token; sequential ids are not enumerable.
#15  GET/HEAD /health answers 200 {"status": "ok"} without a token (Terraform ALB health check, Docker healthcheck).
#16  docs/security-endpoint-matrix.md is the source of truth: every documented route is called with every token and
     the server must accept exactly the tokens the matrix lists; every route the server dispatches must be documented;
     the documented JSON body limit equals server.Handler.MAX_BODY_BYTES.
"""

from __future__ import annotations

import http.client
import json
import re
import threading
import time
from pathlib import Path

import pytest

import server

ROOT = Path(server.__file__).resolve().parent
MATRIX = ROOT / "docs" / "security-endpoint-matrix.md"

TOKENS = {
    "requester": "test-requester-token",
    "operator": "test-operator-token",
    "edge": "test-edge-token",
    "admin": "test-admin-token",
}
TOKEN_ENV = {
    "requester": "NIMBUS_REQUESTER_TOKEN",
    "operator": "NIMBUS_OPERATOR_TOKEN",
    "edge": "NIMBUS_EDGE_TOKEN",
    "admin": "NIMBUS_ADMIN_TOKEN",
}
ROLES = ("requester", "operator", "edge", "admin")


@pytest.fixture()
def secured(tmp_path, monkeypatch):
    """Server with auth enforced (as in production) and one token per role; no master token, no demo faults."""
    monkeypatch.setenv("NIMBUS_TEST_AUTH_CHECK", "1")
    monkeypatch.setenv("NIMBUS_TICK_S", "0")
    for name in ("NIMBUS_AUTH_DISABLED", "NIMBUS_AUTH_TOKEN", "NIMBUS_FAULT_TOKEN", "NIMBUS_DEMO_FAULTS"):
        monkeypatch.delenv(name, raising=False)
    for role, env in TOKEN_ENV.items():
        monkeypatch.setenv(env, TOKENS[role])
    httpd = server.make_server("127.0.0.1", 0, tmp_path / "data")
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield httpd
    httpd.shutdown()
    httpd.server_close()


def call(httpd, method: str, path: str, body: bytes | dict | None = None, token: str | None = None,
         headers: dict | None = None) -> tuple[int, dict, dict]:
    """One HTTP call against the test server; returns (status, json body or {}, response headers)."""
    host, port = httpd.server_address[:2]
    conn = http.client.HTTPConnection(host, port, timeout=10)
    raw = json.dumps(body).encode("utf-8") if isinstance(body, dict) else body
    hdrs = dict(headers or {})
    if raw is not None:
        hdrs.setdefault("Content-Type", "application/json")
        hdrs.setdefault("Content-Length", str(len(raw)))
    if token:
        hdrs["Authorization"] = f"Bearer {token}"
    conn.request(method, path, body=raw, headers=hdrs)
    resp = conn.getresponse()
    data = resp.read()
    conn.close()
    try:
        parsed = json.loads(data.decode("utf-8")) if data else {}
    except ValueError:
        parsed = {}
    return resp.status, parsed, dict(resp.getheaders())


def make_task(httpd) -> str:
    status, body, _ = call(httpd, "POST", "/requests",
                           {"text": "Deliver a wheelchair to ward 3, routine.", "message_id": f"m-{time.time_ns()}"},
                           token=TOKENS["requester"])
    assert status == 201, body
    return body["task_id"]


# -- #14 -------------------------------------------------------------------------------------------------------

def test_issue14_task_detail_needs_a_requester_or_operator_token(secured):
    task_id = make_task(secured)
    for token in (None, "wrong-token"):
        status, body, _ = call(secured, "GET", f"/tasks/{task_id}", token=token)
        assert status == 401, (token, status, body)
        assert "request_text" not in body
    assert call(secured, "GET", f"/tasks/{task_id}", token=TOKENS["requester"])[0] == 200
    assert call(secured, "GET", f"/tasks/{task_id}", token=TOKENS["operator"])[0] == 200
    assert call(secured, "GET", f"/tasks/{task_id}", token=TOKENS["edge"])[0] == 401


def test_issue14_sequential_task_ids_are_not_enumerable_without_a_token(secured):
    for _ in range(3):
        make_task(secured)
    for n in range(1, 6):
        status, body, _ = call(secured, "GET", f"/tasks/task-{n:06d}")
        assert status == 401 and "request_text" not in body, (n, status)


def test_issue14_map_json_does_not_leak_every_task_without_a_token(secured):
    make_task(secured)
    status, body, _ = call(secured, "GET", "/map.json")
    assert status == 401 and "tasks" not in body
    status, body, _ = call(secured, "GET", "/map.json", token=TOKENS["operator"])
    assert status == 200 and body.get("tasks")


def test_issue14_task_list_stays_operator_only(secured):
    make_task(secured)
    assert call(secured, "GET", "/tasks")[0] == 401
    assert call(secured, "GET", "/tasks", token=TOKENS["requester"])[0] == 401
    assert call(secured, "GET", "/tasks", token=TOKENS["operator"])[0] == 200


# -- #15 -------------------------------------------------------------------------------------------------------

def test_issue15_health_answers_200_without_a_token(secured):
    status, body, _ = call(secured, "GET", "/health")
    assert status == 200 and body == {"status": "ok"}
    status, _, headers = call(secured, "HEAD", "/health")
    assert status == 200 and headers.get("Content-Type") == "application/json"


def test_issue15_terraform_and_docker_probe_the_route_that_exists():
    main_tf = (ROOT / "infra" / "terraform" / "main.tf").read_text(encoding="utf-8")
    match = re.search(r"health_check\s*\{(.*?)\}", main_tf, re.S)
    assert match, "infra/terraform/main.tf has no health_check block"
    health = match.group(1)
    assert re.search(r'path\s*=\s*"/health"', health) and re.search(r'matcher\s*=\s*"200"', health)
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "/health" in dockerfile.split("HEALTHCHECK", 1)[1]


# -- #16 -------------------------------------------------------------------------------------------------------

def test_issue16_edge_token_can_request_a_result_upload_target(secured):
    task_id = make_task(secured)
    status, body, _ = call(secured, "POST", "/results/upload-url", {"task_id": task_id, "name": "proof.jpg"},
                           token=TOKENS["edge"])
    assert status == 201, body
    status, _, _ = call(secured, "PUT", f"/results/upload/{task_id}/proof.jpg", b"jpegbytes", token=TOKENS["edge"],
                        headers={"Content-Type": "application/octet-stream"})
    assert status == 201


def test_issue16_body_limit_in_docs_matches_the_server(secured):
    limit = server.Handler.MAX_BODY_BYTES
    doc = MATRIX.read_text(encoding="utf-8")
    assert f"{limit:,} bytes" in doc, "docs/security-endpoint-matrix.md must state the JSON body limit"
    status, body, _ = call(secured, "POST", "/requests", b"{}", token=TOKENS["requester"],
                           headers={"Content-Length": str(limit + 1)})
    assert status == 400 and "exceeds limit" in body.get("error", "")


# -- #16: the matrix is the source of truth ----------------------------------------------------------------------

def documented_routes() -> list[tuple[str, str, set[str]]]:
    """(method, path template, accepted tokens) for every row of the matrix table in section 2."""
    rows = []
    for line in MATRIX.read_text(encoding="utf-8").splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 4 or not cells[0].startswith("`/"):
            continue
        accepted = {t.strip().lower() for t in cells[3].replace("*", "").split(",") if t.strip()}
        for path in re.findall(r"`(/[^`]*)`", cells[0]):
            for method in re.findall(r"`(GET|POST|PUT|HEAD)`", cells[1]):
                rows.append((method, path, accepted))
    return rows


def test_issue16_matrix_parses_and_uses_known_token_names():
    rows = documented_routes()
    assert len(rows) >= 35, f"matrix table not found or truncated ({len(rows)} rows)"
    for method, path, accepted in rows:
        assert accepted, (method, path)
        assert accepted <= {"public", *ROLES}, (method, path, accepted)
        assert accepted == {"public"} or "public" not in accepted, (method, path, accepted)


def _concrete(path: str, task_id: str) -> str:
    return (path.replace("{id}", task_id).replace("{task_id}", task_id).replace("{name}", "proof.jpg")
            .replace("{schema}", "lease"))


def _body_for(path: str, task_id: str, n: int) -> dict:
    if path == "/llm/outage":
        return {"seconds": 0}
    if path == "/fault":
        return {"profile": "healthy"}
    if path == "/results/upload-url":
        return {"task_id": task_id, "name": "proof.jpg"}
    return {"message_id": f"matrix-{n}", "text": "Deliver a wheelchair to ward 3, routine.", "action": "pause"}


def test_issue16_server_enforces_exactly_the_documented_tokens(secured):
    task_id = make_task(secured)
    mismatches = []
    n = 0
    for method, path, accepted in documented_routes():
        url = _concrete(path, task_id)
        public = accepted == {"public"}
        for who in (None, "wrong", *ROLES):
            n += 1
            if who is None:
                token = None
            elif who == "wrong":
                token = "not-a-valid-token"
            else:
                token = TOKENS[who]
            if method in ("POST", "PUT"):
                body = b"x" if method == "PUT" else _body_for(path, task_id, n)
                status, _, _ = call(secured, method, url, body, token=token,
                                    headers={"Content-Type": "application/octet-stream"} if method == "PUT" else None)
            else:
                status, _, _ = call(secured, method, url, token=token)
            allowed = status not in (401, 403)
            should = public or (who in accepted)
            if allowed != should:
                mismatches.append(f"{method} {path} token={who}: HTTP {status}, matrix says "
                                  f"{'allowed' if should else 'rejected'}")
    assert not mismatches, "\n".join(mismatches)


def test_issue16_every_route_the_server_dispatches_is_documented():
    source = (ROOT / "server.py").read_text(encoding="utf-8")
    dispatch = source[source.index("    def do_GET(self):"):source.index("    def _row(self")]
    served = set(re.findall(r'path == "(/[^"]*)"', dispatch))
    for group in re.findall(r"path in \(([^)]*)\)", dispatch):
        served |= set(re.findall(r'"(/[^"]*)"', group))
    documented = {path for _, path, _ in documented_routes()}
    missing = sorted(p for p in served if p not in documented)
    assert not missing, f"routes served by server.py but missing from the matrix: {missing}"
