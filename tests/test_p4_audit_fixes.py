"""Regression tests for the P4 fixes from the final red-team audit (NIM-* ids in the PR description).

Each test pins one defect that was reproduced on main @ 5ea3e6a: public task data, the missing /health route,
upload-route roles and empty uploads, the local reset-memory touching DynamoDB, concurrent clarification answers,
cancel overwriting a completed delivery, cross-origin writes to an auth-disabled server, fault profile names,
the default bind host, and security headers.
"""

import http.client
import json
import threading
import time
from pathlib import Path
from urllib import request as urlreq
from urllib.error import HTTPError
from urllib.parse import urlparse

import pytest

import server

TOKENS = {
    "NIMBUS_REQUESTER_TOKEN": "req-token-1",
    "NIMBUS_OPERATOR_TOKEN": "op-token-1",
    "NIMBUS_EDGE_TOKEN": "edge-token-1",
    "NIMBUS_ADMIN_TOKEN": "admin-token-1",
}


def call(method, url, body=None, token=None, headers=None):
    data = None if body is None else json.dumps(body).encode("utf-8")
    r = urlreq.Request(url, data=data, method=method)
    if data is not None:
        r.add_header("Content-Type", "application/json")
    if token:
        r.add_header("Authorization", f"Bearer {token}")
    for k, v in (headers or {}).items():
        r.add_header(k, v)
    try:
        resp = urlreq.urlopen(r)
    except HTTPError as err:
        resp = err
    with resp:
        raw = resp.read()
        try:
            payload = json.loads(raw.decode("utf-8")) if raw else {}
        except ValueError:
            payload = {}
        return resp.status if hasattr(resp, "status") else resp.code, payload, dict(resp.headers)


@pytest.fixture()
def secured(monkeypatch):
    """Enforce auth with all four role tokens configured."""
    monkeypatch.setenv("NIMBUS_TEST_AUTH_CHECK", "1")
    monkeypatch.delenv("NIMBUS_AUTH_DISABLED", raising=False)
    monkeypatch.delenv("NIMBUS_DEMO_FAULTS", raising=False)
    monkeypatch.delenv("NIMBUS_AUTH_TOKEN", raising=False)
    for k, v in TOKENS.items():
        monkeypatch.setenv(k, v)
    return TOKENS


@pytest.fixture()
def live(tmp_path, monkeypatch):
    """A server whose orchestrator the test can reach (the shared `api` fixture only returns a URL)."""
    monkeypatch.setenv("NIMBUS_TICK_S", "0")
    httpd = server.make_server("127.0.0.1", 0, tmp_path / "data")
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield httpd, f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


def _leased_task(api, token=None):
    status, body, _ = call("POST", api + "/requests",
                           {"text": "Deliver a wheelchair to ward 3, routine.", "message_id": f"m-{time.time_ns()}"},
                           token=token)
    assert status == 201, body
    return body["task_id"]


# -- NIM-C02: task data is never public ---------------------------------------------------------------

def test_task_data_needs_a_token_and_map_json_is_operator_only(api, secured):
    task_id = _leased_task(api, token=secured["NIMBUS_REQUESTER_TOKEN"])

    for path in ("/map.json", f"/tasks/{task_id}", f"/tasks/{task_id}/timeline", f"/tasks/{task_id}/trace", "/tasks"):
        status, body, _ = call("GET", api + path)
        assert status == 401, (path, body)
        assert "request_text" not in json.dumps(body)

    req = secured["NIMBUS_REQUESTER_TOKEN"]
    assert call("GET", api + f"/tasks/{task_id}", token=req)[0] == 200
    assert call("GET", api + f"/tasks/{task_id}/timeline", token=req)[0] == 200
    assert call("GET", api + "/tasks", token=req)[0] == 200
    assert call("GET", api + "/map.json", token=req)[0] == 401          # every task + notices: operator only
    assert call("GET", api + f"/tasks/{task_id}/trace", token=req)[0] == 401

    op = secured["NIMBUS_OPERATOR_TOKEN"]
    assert call("GET", api + "/map.json", token=op)[0] == 200
    assert call("GET", api + f"/tasks/{task_id}/trace", token=op)[0] == 200


def test_admin_token_is_accepted_for_requester_and_edge_routes(api, secured):
    adm = secured["NIMBUS_ADMIN_TOKEN"]
    task_id = _leased_task(api, token=adm)
    status, _, _ = call("POST", api + "/fleet/heartbeat", {"cluster_id": "east-wing"}, token=adm)
    assert status != 401
    assert call("GET", api + f"/tasks/{task_id}", token=adm)[0] == 200


def test_get_fault_is_readable_by_the_operator_but_only_admin_can_change_it(api, secured):
    op, adm = secured["NIMBUS_OPERATOR_TOKEN"], secured["NIMBUS_ADMIN_TOKEN"]
    assert call("GET", api + "/fault", token=op)[0] == 200
    assert call("POST", api + "/fault", {"profile": "severe"}, token=op)[0] in (401, 403)
    assert call("POST", api + "/fault", {"profile": "healthy"}, token=adm)[0] == 200


# -- NIM-H01: /health exists and is public -------------------------------------------------------------

def test_health_is_routed_and_public(api, secured):
    status, body, _ = call("GET", api + "/health")
    assert status == 200 and body == {"ok": True}


# -- NIM-M02: upload routes accept the edge token, refuse empty / length-less / finished-task uploads ----

def test_edge_token_gets_an_upload_target_and_can_put(api, secured):
    edge = secured["NIMBUS_EDGE_TOKEN"]
    task_id = _leased_task(api, token=secured["NIMBUS_REQUESTER_TOKEN"])
    status, target, _ = call("POST", api + "/results/upload-url", {"task_id": task_id, "name": "proof.jpg"}, token=edge)
    assert status == 201, target

    u = urlparse(api)
    conn = http.client.HTTPConnection(u.hostname, u.port, timeout=10)
    conn.request("PUT", f"/results/upload/{task_id}/proof.jpg", body=b"jpegbytes",
                 headers={"Authorization": f"Bearer {edge}", "Content-Length": "9"})
    resp = conn.getresponse()
    assert resp.status == 201, resp.read()
    conn.close()


def _put_raw(api, path, token, headers, body=b""):
    u = urlparse(api)
    conn = http.client.HTTPConnection(u.hostname, u.port, timeout=10)
    conn.putrequest("PUT", path)
    conn.putheader("Authorization", f"Bearer {token}")
    for k, v in headers.items():
        conn.putheader(k, v)
    conn.endheaders()
    if body:
        conn.send(body)
    resp = conn.getresponse()
    status = resp.status
    resp.read()
    conn.close()
    return status


def test_put_without_length_or_with_zero_length_is_refused(api, secured):
    edge = secured["NIMBUS_EDGE_TOKEN"]
    task_id = _leased_task(api, token=secured["NIMBUS_REQUESTER_TOKEN"])
    path = f"/results/upload/{task_id}/proof.jpg"
    assert _put_raw(api, path, edge, {"Transfer-Encoding": "chunked"}, b"5\r\nhello\r\n0\r\n\r\n") == 411
    assert _put_raw(api, path, edge, {"Content-Length": "0"}) == 400


def test_uploads_for_a_finished_task_are_refused(api, secured):
    edge, op = secured["NIMBUS_EDGE_TOKEN"], secured["NIMBUS_OPERATOR_TOKEN"]
    task_id = _leased_task(api, token=secured["NIMBUS_REQUESTER_TOKEN"])
    assert call("POST", api + f"/tasks/{task_id}/control", {"action": "cancel", "message_id": "c-1"}, token=op)[0] == 201
    assert call("POST", api + "/results/upload-url", {"task_id": task_id, "name": "proof.jpg"}, token=edge)[0] == 409
    assert _put_raw(api, f"/results/upload/{task_id}/proof.jpg", edge, {"Content-Length": "3"}, b"abc") == 409


# -- NIM-H03: a local reset-memory never builds an AWS client -------------------------------------------

def test_local_reset_memory_never_touches_dynamodb(api, monkeypatch):
    import boto3
    from cloud import durable

    attempts = []

    def refuse(*a, **kw):          # main swallowed this error, so record the attempt rather than rely on it
        attempts.append(a)
        raise RuntimeError("a local server must not build an AWS client")

    monkeypatch.setattr(boto3, "client", refuse)
    monkeypatch.setattr(durable.DynamoDurable, "from_env", classmethod(lambda cls: refuse("DynamoDurable.from_env")))
    status, body, _ = call("POST", api + "/reset-memory", {})
    assert status == 200, body
    assert attempts == [], attempts
    assert body["dynamodb_deleted"] == []


# -- NIM-H06: two concurrent answers to one question give one lease --------------------------------------

def test_concurrent_clarification_answers_issue_one_lease(live):
    httpd, api = live
    status, body, _ = call("POST", api + "/requests", {"text": "Need an infusion pump at 2B-12, urgent.", "message_id": "sc1"})
    assert status == 201 and body["status"] == "needs_clarification", body
    task_id = body["task_id"]

    original = httpd.orch.handle_request

    def slow(*a, **kw):                 # model latency: the window in which a second answer used to slip in
        time.sleep(0.6)
        return original(*a, **kw)

    httpd.orch.handle_request = slow
    results = []

    def answer(i):
        results.append(call("POST", api + f"/requests/{task_id}/answer",
                            {"text": "Yes, a paediatric pump please.", "message_id": f"ans-{i}"})[0])

    threads = [threading.Thread(target=answer, args=(i,)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == [201, 409], results
    leases = [o for o in httpd.store.outbox()
              if str(o.get("topic", "")).endswith("/lease") and isinstance(o.get("payload"), dict)
              and str(o["payload"].get("lease_id", "")).startswith(f"lease-{task_id}-")]
    assert len(leases) == 1, leases


# -- NIM-M01: a cancel that loses the race to OUTPUT_READY does not overwrite the completion ----------------

def test_cancel_racing_completion_keeps_the_completed_delivery(live, monkeypatch):
    httpd, api = live
    task_id = _leased_task(api)
    task = httpd.store.get_task(task_id)
    version = task["lease"]["version"]

    original = server.contracts.validate_document

    def complete_meanwhile(kind, doc):
        if kind == "decision_log_entry" and doc.get("output", {}).get("decision") == "operator_cancel":
            status, body, _ = call("POST", api + "/escalations", {
                "type": "OUTPUT_READY", "message_id": "done-1", "lease_version": version, "task_id": task_id,
                "payload": {"result_ref": f"storage://results/{task_id}/proof.jpg"}})
            assert status == 201, body
        return original(kind, doc)

    monkeypatch.setattr(server.contracts, "validate_document", complete_meanwhile)
    status, body, _ = call("POST", api + f"/tasks/{task_id}/control", {"action": "cancel", "message_id": "c-race"})
    assert status == 409, body
    assert httpd.store.get_task(task_id)["status"] == "completed"


# -- NIM-M14: an auth-disabled server refuses cross-origin browser writes; binds loopback by default ------

def test_cross_origin_writes_are_refused_when_auth_is_disabled(api):
    host = urlparse(api).netloc
    status, body, _ = call("POST", api + "/requests", {"text": "wheelchair to ward 3", "message_id": "x-1"},
                           headers={"Origin": "http://evil.example"})
    assert status == 403, body
    assert call("POST", api + "/requests", {"text": "wheelchair to ward 3", "message_id": "x-2"},
                headers={"Origin": f"http://{host}"})[0] == 201
    assert call("POST", api + "/requests", {"text": "wheelchair to ward 3", "message_id": "x-3"})[0] == 201


def test_default_bind_host_is_loopback_outside_production(monkeypatch):
    for k in ("NIMBUS_BIND_HOST", "NIMBUS_BACKEND", "ENVIRONMENT"):
        monkeypatch.delenv(k, raising=False)
    assert server.default_bind_host() == "127.0.0.1"
    monkeypatch.setenv("NIMBUS_BACKEND", "aws")
    assert server.default_bind_host() == "0.0.0.0"
    monkeypatch.setenv("NIMBUS_BIND_HOST", "192.0.2.10")
    assert server.default_bind_host() == "192.0.2.10"


def test_dockerfile_binds_all_interfaces_for_the_container():
    dockerfile = (Path(server.__file__).resolve().parent / "Dockerfile").read_text(encoding="utf-8")
    assert "NIMBUS_BIND_HOST=0.0.0.0" in dockerfile


# -- NIM-L02: the harness's own profile names reach the server -----------------------------------------------

def test_fault_accepts_named_custom_profiles_with_parameters(api):
    status, body, _ = call("POST", api + "/fault", {"profile": "env", "latency_ms": 120, "loss_rate": 0.1})
    assert status == 200 and body["fault"]["profile"] == "env", body
    status, body, _ = call("POST", api + "/fault", {"profile": "trace@12s", "latency_ms": 40})
    assert status == 200, body
    assert call("POST", api + "/fault", {"profile": "no-such-profile"})[0] == 400
    assert call("POST", api + "/fault", {"profile": "healthy"})[0] == 200


# -- carried over from PR #10 (closed): lease timestamp validation and Terraform baselines ----------------------

def test_semantic_lease_errors_strict_validation():
    """PR #10 D: offset-aware ISO-8601 timestamps, presence, and deadline <= expiry; never raises."""
    import contracts

    base = {"lease_id": "lease-001", "deadline_ts": "2026-10-02T10:12:00Z", "expiry_ts": "2026-10-02T10:15:00Z"}
    assert contracts.semantic_lease_errors(base) == []
    assert any("deadline_ts: field is required" in e
               for e in contracts.semantic_lease_errors({"expiry_ts": "2026-10-02T10:15:00Z"}))
    assert any("expiry_ts: field is required" in e
               for e in contracts.semantic_lease_errors({"deadline_ts": "2026-10-02T10:12:00Z"}))
    assert any("must be an ISO-8601 string" in e
               for e in contracts.semantic_lease_errors({"deadline_ts": 12345, "expiry_ts": "2026-10-02T10:15:00Z"}))
    assert any("invalid ISO-8601 timestamp" in e
               for e in contracts.semantic_lease_errors({"deadline_ts": "not-a-timestamp", "expiry_ts": "2026-10-02T10:15:00Z"}))
    assert any("must be offset-aware" in e
               for e in contracts.semantic_lease_errors({"deadline_ts": "2026-10-02T10:12:00", "expiry_ts": "2026-10-02T10:15:00"}))
    assert contracts.semantic_lease_errors({"deadline_ts": "2026-10-02T10:12:00+05:30", "expiry_ts": "2026-10-02T10:15:00+05:30"}) == []
    assert any("must be <= expiry_ts" in e
               for e in contracts.semantic_lease_errors({"deadline_ts": "2026-10-02T10:20:00Z", "expiry_ts": "2026-10-02T10:15:00Z"}))
    assert contracts.semantic_lease_errors(None) == ["$: lease must be a JSON object"]
    assert contracts.semantic_lease_errors("string") == ["$: lease must be a JSON object"]


TF_DIR = Path(server.__file__).resolve().parent / "infra" / "terraform"


def test_terraform_public_ip_is_derived_from_egress_mode():
    """NIM-H04 / PR #10 B1: the default stack must be able to reach ECR and AWS APIs."""
    variables = (TF_DIR / "variables.tf").read_text(encoding="utf-8")
    main = (TF_DIR / "main.tf").read_text(encoding="utf-8")
    block = variables[variables.index('variable "assign_public_ip"'):]
    assert "default     = null" in block[:block.index("}") + 1]
    assert 'var.assign_public_ip != null ? var.assign_public_ip : var.egress_mode == "public_ip"' in main
    assert "assign_public_ip = local.assign_public_ip" in main


def test_terraform_iot_arns_have_no_mqtt_wildcards_and_subscribe_uses_topicfilter():
    """NIM-M23 / PR #10 B2: IAM treats MQTT '+' literally; Subscribe needs topicfilter/ ARNs; probe is cloud -> edge."""
    import re

    for name in ("main.tf", "cloud.tf"):
        text = (TF_DIR / name).read_text(encoding="utf-8")
        arns = re.findall(r'"(arn:aws:iot:[^"]*)"', text)
        assert arns, name
        assert not [a for a in arns if "+" in a], (name, arns)
        # each statement's text runs from its Action to the closing brace of the statement object
        subscribe = re.findall(r'Action\s*=\s*\["iot:Subscribe"\](.*?)\n\s*\}', text, re.S)
        for stmt in subscribe:
            assert "topicfilter/" in stmt and ":topic/" not in stmt, (name, stmt)

    main = (TF_DIR / "main.tf").read_text(encoding="utf-8")
    edge = main[main.index('resource "aws_iot_policy" "edge_cluster"'):]
    publish = re.search(r'Action\s*=\s*\["iot:Publish"\](.*?)\n\s*\}', edge, re.S).group(1)
    receive = re.search(r'Action\s*=\s*\["iot:Receive"\](.*?)\n\s*\}', edge, re.S).group(1)
    assert "probe" not in publish and "probe" in receive


def test_terraform_s3_security_baselines():
    """PR #10 B3: both buckets private, owner-enforced and encrypted; results versioned; static app readable via OAC."""
    main = (TF_DIR / "main.tf").read_text(encoding="utf-8")
    for bucket in ("outputs", "static_app"):
        assert f'resource "aws_s3_bucket_public_access_block" "{bucket}"' in main
        assert f'resource "aws_s3_bucket_ownership_controls" "{bucket}"' in main
        assert f'resource "aws_s3_bucket_server_side_encryption_configuration" "{bucket}"' in main
    assert 'resource "aws_s3_bucket_versioning" "outputs"' in main
    assert 'resource "aws_s3_bucket_policy" "static_app"' in main and "AllowCloudFrontOAC" in main


# -- security headers ------------------------------------------------------------------------------------------

def test_pages_and_json_send_security_headers(api):
    status, _, headers = call("GET", api + "/")
    assert status == 200
    assert headers.get("X-Content-Type-Options") == "nosniff"
    assert headers.get("X-Frame-Options") == "DENY"
    status, _, headers = call("GET", api + "/health")
    assert headers.get("X-Content-Type-Options") == "nosniff"
    assert headers.get("Cache-Control") == "no-store"
