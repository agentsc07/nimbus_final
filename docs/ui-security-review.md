# UI Security and State Correctness Review

**Components:** `static/index.html` + `static/app.js` (requester app, served at `/`), `static/operator.html` +
`static/operator.js` (operator console, `/operator`), `static/map.html` (live map, `/map`). All are served by `server.py`.
**Scope:** HTML injection (XSS), Content Security Policy and response headers, token handling, polling and stale state,
cancel/pause presentation.
**Status:** corrected on 12 Nov 2026. An earlier version quoted a strict CSP that the pages do not use, and described a
"Network Disconnected" banner, monotonic state sequencing and a `CANCEL_REQUESTED -> ... -> ROBOT_STOPPED` cancel
chain that do not exist in the code. Those claims are withdrawn; this page describes what the code does.

---

## 1. HTML injection (XSS)

Untrusted strings reach the pages from the API: request text, task/lease/robot/cluster ids, notices, questions, error
messages, inventory keys.

- `static/app.js` and `static/operator.js` each define an `esc()` helper that escapes `& < > " '`, and wrap the values
  they interpolate into `innerHTML` templates with it (task rows, badges, detail panels). This review did not re-check
  every template one by one.
- `static/map.html` builds its DOM and SVG with `createElement` / `createElementNS` and `textContent`; it does not use
  `innerHTML`.
- There is no automated XSS regression test in `tests/`.

## 2. Content Security Policy

`index.html` and `operator.html` carry this policy as a `<meta http-equiv>` tag; `map.html` has none. There is no CSP
response header.

```html
<meta http-equiv="Content-Security-Policy" content="default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; connect-src 'self' *; img-src 'self' data:;">
```

What it does and does not do:

- `'unsafe-inline'` in `script-src` means injected inline scripts and event-handler attributes would run: the CSP is not
  an XSS defence; escaping (section 1) is the only one.
- `https://cdn.jsdelivr.net` allows any script published on that CDN.
- `connect-src 'self' *` allows `fetch` to any origin, so it does not limit where a script could send data.
- A meta CSP cannot set `frame-ancestors`; framing is handled by the `X-Frame-Options` header below.

Tightening it (dropping `'unsafe-inline'` by moving inline scripts and styles into files, pinning or self-hosting the
CDN script, `connect-src 'self'`, and sending it as a header) is open work.

## 3. Response headers

`server.py` sends, on the static pages, `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY` and
`Referrer-Policy: no-referrer`; JSON responses carry `X-Content-Type-Options: nosniff` and `Cache-Control: no-store`.
There is no `Strict-Transport-Security`: the server itself speaks plain HTTP, and HTTPS exists only on the API Gateway
hostname.

## 4. Tokens in the browser

- The requester app and operator console read a bearer token from the URL fragment (`/#token=...`,
  `/operator#token=...`; a fragment is never sent to the server), remove it from the address bar and history, and keep
  it in `sessionStorage` for that tab only (separate keys for the two apps). Both also accept it pasted into the banner
  described below.
- The map page (`/map#token=...`) reads the token from the fragment on every load and sends it, but does not store it,
  strip it from the address bar or show a banner (it is P3's page and was not changed in this pass).
- Every API call sends the token as `Authorization: Bearer <token>`.
- On a 401 or 403 the requester app and console show a banner asking for a token (or saying the token is not allowed to
  do that).
- Which token each page needs: requester token (or operator/master) for the requester app; operator token for the
  console and for `/map.json`. See `docs/security-endpoint-matrix.md`.
- With `NIMBUS_AUTH_DISABLED=1` (honoured only outside production) no token is needed, and the server refuses
  cross-origin browser POSTs (an `Origin` header that does not match `Host`) with 403, so another web page cannot drive a
  local demo server.

## 5. Polling and stale state

- The operator console refreshes tasks, fleet and fault status every 2 s and the model status every 5 s. The task
  refresh has an in-flight flag (`_refreshTasksInProgress`), so a slow `/tasks` call is not overlapped by the next one;
  the other refreshes have no such flag. The task detail panel (in both apps) drops a response that arrives after the
  operator or requester has selected another task, and the console's Pause/Cancel buttons post to the task shown in the
  panel, not to whichever task is selected when the click lands.
- When a refresh fails (non-200 or a network error), the previously rendered rows stay on screen. There is no
  "disconnected" indicator other than the 401/403 banner.
- The requester app polls every 3 s.

## 6. Cancel and pause

When the operator presses Cancel or Pause, the console disables the button and shows "Cancelling..." / "Pausing..."
while `POST /tasks/{id}/control` is in flight, alerts if the cloud did not record the intent, and then re-renders from
the task status the cloud reports. The status shown is the cloud's: the console has no separate "awaiting edge
acknowledgement" or "robot stopped" state, so a cancelled task can be shown as cancelled before the edge has received
the stop lease.
