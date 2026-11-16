# Security Endpoint Matrix: Nimbus P4 API Authorization

**Scope:** The complete HTTP ingress surface of `server.py` on `main`, as enforced by `server.py:_is_authorized`.
**Source of truth:** this table. `tests/test_p4_issues_14_15_16.py` calls every route below with no token, a wrong
token and each role's token, and fails if the server accepts or rejects anything differently. It also fails if
`server.py` serves a route that is missing here.
**Auth implementation:** fail-closed bearer tokens (`Authorization: Bearer <token>` or `X-Nimbus-Token: <token>`).
**Bypass:** `NIMBUS_AUTH_DISABLED=1` for local runs only; it is ignored when `NIMBUS_BACKEND=aws` or
`ENVIRONMENT=production`.
**Deployment note:** the AWS deployment measured on 7 Nov 2026 ran an image built before fail-closed auth; this matrix
describes the code, not that build.

---

## 1. Roles and tokens

| Role | Environment variable | What it is for | Tokens accepted for this role |
| :--- | :--- | :--- | :--- |
| **Public** | *none* | Static pages, `/pack`, `/ui-config`, `/health`, `/schemas/*` | no token needed |
| **Requester** | `NIMBUS_REQUESTER_TOKEN` | Submit requests, answer clarifications, read one task's status | requester, operator |
| **Operator** | `NIMBUS_OPERATOR_TOKEN` | Task lists, timelines and traces, the live map, telemetry, inventory, pause/cancel/replan, corridor reopen, memory reset | operator, admin |
| **Edge** | `NIMBUS_EDGE_TOKEN` | Check-ins, escalations (`CLARIFY`, `UNEXPECTED_EVENT`, `OUTPUT_READY`), heartbeats, relay decisions, pulling the outbox, result upload (FR-10) | edge, operator |
| **Admin / Fault** | `NIMBUS_ADMIN_TOKEN` (or `NIMBUS_FAULT_TOKEN`) | Fault injection and model-outage simulation | admin |
| **Master** | `NIMBUS_AUTH_TOKEN` | Fallback for deployment pipelines and end-to-end harnesses | accepted on every protected route |

The cross-role acceptances are intentional: the operator console submits demo requests and can act as an edge in the
map page's simulated-edge mode, and admin is a superset of operator. Admin is not accepted on requester or edge routes.
`NIMBUS_DEMO_FAULTS=1` opens the admin routes without a token outside production.

---

## 2. Endpoint matrix

Accepted tokens are listed by role; the master token (`NIMBUS_AUTH_TOKEN`) is accepted on every non-public route and is
not repeated. "Without a valid token" is what a missing or wrong token gets.

| Endpoint | Method | Role | Accepted tokens | Without a valid token | Test |
| :--- | :---: | :--- | :--- | :--- | :--- |
| `/` | `GET` | Public | public | 200 | `test_p4_security.py::test_public_routes_accessible_without_auth` |
| `/app.js` | `GET` | Public | public | 200 | `test_p4_issues_14_15_16.py` (matrix test) |
| `/operator` | `GET` | Public | public | 200 | `test_api.py::test_operator_page_served` |
| `/operator.js` | `GET` | Public | public | 200 | `test_api.py::test_operator_page_served` |
| `/map` | `GET` | Public | public | 200 | `test_p4_issues_14_15_16.py` (matrix test) |
| `/pack` | `GET` | Public | public | 200 | `test_p4_security.py::test_public_routes_accessible_without_auth` |
| `/ui-config` | `GET` | Public | public | 200 | `test_p4_issues_14_15_16.py` (matrix test) |
| `/health` | `GET`, `HEAD` | Public | public | 200 `{"status": "ok"}` | `test_p4_issues_14_15_16.py::test_issue15_health_answers_200_without_a_token` |
| `/schemas/{schema}` | `GET` | Public | public | 200 | `test_api.py::test_schemas_served_over_http` |
| `/tasks/{id}` | `GET` | Requester | requester, operator | 401 | `test_p4_issues_14_15_16.py::test_issue14_task_detail_needs_a_requester_or_operator_token` |
| `/requests` | `POST` | Requester | requester, operator | 401 | `test_p4_security.py::test_token_authorization_and_role_separation` |
| `/requests/{id}/answer` | `POST` | Requester | requester, operator | 401 | `test_p4_issues_14_15_16.py` (matrix test) |
| `/tasks` | `GET` | Operator | operator, admin | 401 | `test_p4_issues_14_15_16.py::test_issue14_task_list_stays_operator_only` |
| `/tasks/{id}/timeline` | `GET` | Operator | operator, admin | 401 | `test_p4_issues_14_15_16.py` (matrix test) |
| `/tasks/{id}/trace` | `GET` | Operator | operator, admin | 401 | `test_p4_issues_14_15_16.py` (matrix test) |
| `/map.json` | `GET` | Operator | operator, admin | 401 | `test_p4_issues_14_15_16.py::test_issue14_map_json_does_not_leak_every_task_without_a_token` |
| `/fleet` | `GET` | Operator | operator, admin | 401 | `test_p4_security.py::test_unauthorized_access_all_protected_get_endpoints` |
| `/trace` | `GET` | Operator | operator, admin | 401 | `test_p4_security.py::test_unauthorized_access_all_protected_get_endpoints` |
| `/notifications` | `GET` | Operator | operator, admin | 401 | `test_p4_issues_14_15_16.py` (matrix test) |
| `/cost` | `GET` | Operator | operator, admin | 401 | `test_p4_security.py::test_unauthorized_access_all_protected_get_endpoints` |
| `/metrics` | `GET` | Operator | operator, admin | 401 | `test_p4_security.py::test_unauthorized_access_all_protected_get_endpoints` |
| `/inventory` | `GET` | Operator | operator, admin | 401 | `test_p4_security.py::test_unauthorized_access_all_protected_get_endpoints` |
| `/llm-status` | `GET` | Operator | operator, admin | 401 | `test_p4_security.py::test_unauthorized_access_all_protected_get_endpoints` |
| `/tasks/{id}/control` | `POST` | Operator | operator, admin | 401 | `test_p4_issues_14_15_16.py` (matrix test) |
| `/tasks/{id}/replan` | `POST` | Operator | operator, admin | 401 | `test_p4_issues_14_15_16.py` (matrix test) |
| `/map/reopen` | `POST` | Operator | operator, admin | 401 | `test_p4_issues_14_15_16.py` (matrix test) |
| `/inventory/stock` / `/fleet/stock` | `POST` | Operator | operator, admin | 401 | `test_p4_security.py::test_unauthorized_access_all_protected_mutating_endpoints` |
| `/inventory/reset` | `POST` | Operator | operator, admin | 401 | `test_p4_security.py::test_unauthorized_access_all_protected_mutating_endpoints` |
| `/reset-memory` / `/memory/reset` | `POST` | Operator | operator, admin | 401 | `test_p4_security.py::test_unauthorized_access_all_protected_mutating_endpoints` |
| `/checkins` | `POST` | Edge | edge, operator | 401 | `test_p4_security.py::test_unauthorized_access_all_protected_mutating_endpoints` |
| `/escalations` | `POST` | Edge | edge, operator | 401 | `test_p4_security.py::test_unauthorized_access_all_protected_mutating_endpoints` |
| `/fleet/heartbeat` | `POST` | Edge | edge, operator | 401 | `test_p4_security.py::test_unauthorized_access_all_protected_mutating_endpoints` |
| `/relay/decide` | `POST` | Edge | edge, operator | 401 | `test_p4_security.py::test_unauthorized_access_all_protected_mutating_endpoints` |
| `/outbox` | `GET` | Edge | edge, operator | 401 | `test_p4_issues_14_15_16.py` (matrix test) |
| `/results/upload-url` | `POST` | Edge | edge, operator | 401 | `test_p4_issues_14_15_16.py::test_issue16_edge_token_can_request_a_result_upload_target` |
| `/results/upload/{task_id}/{name}` | `PUT` | Edge | edge, operator | 401 | `test_p4_issues_14_15_16.py::test_issue16_edge_token_can_request_a_result_upload_target` |
| `/fault` | `GET`, `POST` | Admin / Fault | admin | 403 without a token, 401 with a wrong one | `test_api.py::test_fault_endpoint_auth_guard` |
| `/llm/outage` | `POST` | Admin / Fault | admin | 403 without a token, 401 with a wrong one | `test_api.py::test_fault_endpoint_auth_guard` |

`/map.html` and `/favicon.ico` are on the public allow-list but are not served (404); the map page is `/map`, and it
fetches `/map.json` with the token given as `/map#token=<operator token>`.

---

## 3. Security properties

1. **Fail-closed default:** if no token is configured for a route's role, that route answers 401 (403 for the admin
   routes). It never runs unauthenticated.
2. **Timing-attack protection:** tokens are compared with `hmac.compare_digest`.
3. **No credential leakage:** errors return generic bodies such as `{"error": "unauthorized", "detail": "Missing
   authorization token"}`; tokens and environment names are never echoed.
4. **Enforced in the container:** authentication runs inside `server.py`, so a request that reaches the container
   without passing API Gateway is still rejected.
5. **Body limits:** `server.py:_read_json` rejects a JSON request body with `Content-Length` above
   `Handler.MAX_BODY_BYTES` = 1,000,000 bytes (about 1 MB) with HTTP 400 before reading it. Result files uploaded with
   `PUT /results/upload/{task_id}/{name}` may be up to `cloud.results.MAX_UPLOAD_BYTES` = 10 MiB (413 above that).
   Cloud-edge messages are under 2 KB (PRD section 5), so 1 MB is a deliberate ceiling, not a constraint on them.
6. **Task data is not public (red-team #14):** a task's request text, lease, robots and route are readable only with a
   requester or operator token (`/tasks/{id}`), and the full list (`/tasks`, `/map.json`) only with an operator token,
   so sequential task ids cannot be enumerated anonymously.
