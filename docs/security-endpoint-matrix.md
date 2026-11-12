# Security Endpoint Matrix: Nimbus API Authorization

**Scope:** every HTTP route of `server.py` on this branch (the same code runs locally and in the ECS task).
**Mechanism:** `server.py:_is_authorized`, a per-route role check on a bearer token, fail-closed.
**Deployment caveat:** the image running in AWS (task definition `nimbus-ds252-app:12`, deployed 7 Nov 2026) predates this
code and has no tokens configured; there, every route except `/fault` and `/llm/outage` was unauthenticated. This page
describes the code, not that deployment (see `docs/aws-integration-audit.md`).

---

## 1. Roles and tokens

A token is sent as `Authorization: Bearer <token>` (or `X-Nimbus-Token: <token>`) and compared with
`hmac.compare_digest`.

| Role | Accepted tokens (environment variables) |
| :--- | :--- |
| **Public** | none needed |
| **Requester** | `NIMBUS_REQUESTER_TOKEN`, `NIMBUS_OPERATOR_TOKEN`, `NIMBUS_ADMIN_TOKEN`, master |
| **Operator** | `NIMBUS_OPERATOR_TOKEN`, `NIMBUS_ADMIN_TOKEN`, master |
| **Edge** | `NIMBUS_EDGE_TOKEN`, `NIMBUS_OPERATOR_TOKEN`, `NIMBUS_ADMIN_TOKEN`, master |
| **Admin / fault** | `NIMBUS_ADMIN_TOKEN` or `NIMBUS_FAULT_TOKEN`, master; outside production also open to anyone when `NIMBUS_DEMO_FAULTS=1` |
| master | `NIMBUS_AUTH_TOKEN` is accepted for every role |

Fail-closed rules:

- A role with **no token configured** answers 401 (`"token for role '<role>' is not configured"`), or 403 for the admin
  routes. A missing token answers 401 (403 for admin routes); a wrong token answers 401.
- `NIMBUS_AUTH_DISABLED=1` turns the check off **only outside production**; production is `NIMBUS_BACKEND=aws` or
  `ENVIRONMENT=production`, where the flag is ignored with a warning. While the check is off, a browser POST/PUT whose
  `Origin` header does not match `Host` is refused with 403, and the edge routes still require `NIMBUS_EDGE_TOKEN` if it
  is set.
- The same bypass applies under pytest (`PYTEST_CURRENT_TEST` set) unless `NIMBUS_TEST_AUTH_CHECK` is set, again only
  outside production.
- Any route not listed below is treated as operator-only before it can answer 404.

## 2. Routes

| Route | Method | Role |
| :--- | :---: | :--- |
| `/`, `/app.js`, `/operator`, `/operator.js`, `/map`, `/map.html` | GET | Public |
| `/pack`, `/ui-config`, `/favicon.ico`, `/schemas/{name}` | GET | Public |
| `/health` (returns `200 {"ok": true}`) | GET | Public |
| `/requests` | POST | Requester |
| `/requests/{task_id}/answer` | POST | Requester |
| `/tasks`, `/tasks/{task_id}`, `/tasks/{task_id}/timeline` | GET | Requester |
| `/tasks/{task_id}/trace`, `/trace` | GET | Operator |
| `/map.json`, `/fleet`, `/notifications`, `/cost`, `/metrics`, `/inventory`, `/llm-status` | GET | Operator |
| `/fault` (read-only status) | GET | Operator (also the admin/fault token) |
| `/tasks/{task_id}/control`, `/tasks/{task_id}/replan` | POST | Operator |
| `/map/reopen` | POST | Operator |
| `/inventory/stock`, `/fleet/stock`, `/inventory/reset` | POST | Operator |
| `/reset-memory`, `/memory/reset` | POST | Operator |
| `/checkins`, `/escalations`, `/fleet/heartbeat`, `/relay/decide` | POST | Edge |
| `/outbox` | GET | Edge |
| `/results/upload-url` | POST | Edge |
| `/results/upload/{task_id}/{name}` (local result store) | PUT | Edge |
| `/fault` | POST | Admin / fault |
| `/llm/outage` | POST | Admin / fault |

## 3. Other properties

1. **Request size:** JSON bodies over 1,000,000 bytes are rejected with 400. `PUT /results/upload/...` requires a
   `Content-Length` (411 without one), refuses an empty body (400), a body over 10 MiB (413) and an upload for a task
   that is already completed, cancelled or rejected (409).
2. **Error bodies** carry a fixed message (`{"error": "unauthorized", "detail": ...}`); they name the role whose token
   is missing but never a token value.
3. **Direct access to the container:** the check runs inside `server.py`, so a request that reaches the container
   without going through API Gateway still needs a token, provided the tokens are configured. Note that the live
   security group allowed port 8000 from the internet and the live image had no tokens.
4. **Bind address:** the server listens on `127.0.0.1` by default; `NIMBUS_BIND_HOST` overrides it, the Dockerfile sets
   `0.0.0.0`, and production mode defaults to `0.0.0.0`.
5. **MQTT and SQS ingest** (`NIMBUS_TRANSPORT=mqtt`, `NIMBUS_SQS_QUEUE_URL`) feed the same check-in and escalation
   handlers without this HTTP check; they rely on the broker's and IAM's access control instead (the MQTT client has no
   TLS or credentials, see `docs/aws-integration-audit.md` section 1).

## 4. Tests

`tests/test_p4_security.py` (`test_public_routes_accessible_without_auth`,
`test_fail_closed_when_auth_enabled_and_tokens_unset`, `test_token_authorization_and_role_separation`) and
`tests/test_api.py::test_fault_endpoint_auth_guard` cover the public routes, fail-closed behaviour, role separation and
the admin routes. Not every route in the table has its own test.
