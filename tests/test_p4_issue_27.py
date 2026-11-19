"""Regression tests for red-team issue #27 (NFR-5): the remediation record said server.py sends a
Content-Security-Policy header, but it sent none; the only CSP was a weaker <meta> tag that allowed
'unsafe-inline' scripts and connections to any host.

What must hold now: every response carries a server-set CSP and nosniff; pages allow scripts only from this origin,
the pinned Three.js CDN and the SHA-256 hashes of their own inline scripts (so they still run); API responses allow
nothing; and no page carries a second, weaker <meta> policy.
"""

from __future__ import annotations

import base64
import hashlib
import re
from urllib import request as urlreq
from urllib.error import HTTPError

import pytest

PAGES = {"/": "index.html", "/operator": "operator.html", "/map": "map.html"}
INLINE_SCRIPT = re.compile(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", re.S | re.I)


def _get(url: str):
    try:
        with urlreq.urlopen(url) as resp:
            return resp.status, resp.headers, resp.read().decode("utf-8")
    except HTTPError as err:
        return err.code, err.headers, err.read().decode("utf-8")


def _directives(csp: str) -> dict[str, list[str]]:
    out = {}
    for part in filter(None, (p.strip() for p in csp.split(";"))):
        name, *values = part.split()
        out[name] = values
    return out


@pytest.mark.parametrize("path", list(PAGES))
def test_issue27_pages_get_a_strict_server_csp(api, path):
    status, headers, _ = _get(api + path)
    assert status == 200
    csp = headers.get("Content-Security-Policy")
    assert csp, f"{path}: no Content-Security-Policy header"
    d = _directives(csp)
    assert d["default-src"] == ["'self'"]
    assert "'unsafe-inline'" not in d["script-src"] and "'unsafe-eval'" not in d["script-src"]
    assert d["connect-src"] == ["'self'"], "the apps only call their own origin"
    assert d["object-src"] == ["'none'"] and d["frame-ancestors"] == ["'none'"] and d["base-uri"] == ["'self'"]
    assert headers.get("X-Content-Type-Options") == "nosniff"


@pytest.mark.parametrize("path", list(PAGES))
def test_issue27_every_inline_script_is_allowed_by_its_hash(api, path):
    _, headers, html = _get(api + path)
    script_src = _directives(headers["Content-Security-Policy"])["script-src"]
    for body in INLINE_SCRIPT.findall(html.replace("\r\n", "\n").replace("\r", "\n")):   # as the browser hashes it
        digest = base64.b64encode(hashlib.sha256(body.encode("utf-8")).digest()).decode()
        assert f"'sha256-{digest}'" in script_src, f"{path}: an inline script would be blocked"


@pytest.mark.parametrize("path", list(PAGES))
def test_issue27_no_page_carries_a_second_weaker_meta_policy(api, path):
    _, _, html = _get(api + path)
    assert not re.search(r"<meta[^>]+http-equiv=[\"']Content-Security-Policy", html, re.I)


@pytest.mark.parametrize("path", ["/health", "/pack", "/operator.js", "/no-such-route"])
def test_issue27_non_page_responses_allow_nothing(api, path):
    status, headers, _ = _get(api + path)
    assert status in (200, 404)
    d = _directives(headers.get("Content-Security-Policy", ""))
    assert d.get("default-src") == ["'none'"] and d.get("frame-ancestors") == ["'none'"]
    assert headers.get("X-Content-Type-Options") == "nosniff"


def test_issue27_hashes_match_what_a_browser_hashes_for_crlf_files():
    """Browsers hash an inline script after HTML newline normalisation (CRLF and CR become LF). A page checked out
    with CRLF endings (Windows autocrlf) must still get the hash the browser computes, or its script is blocked."""
    import server

    body = "\nconsole.log(1);\n"
    expected = base64.b64encode(hashlib.sha256(body.encode("utf-8")).digest()).decode()
    for html in (f"<script>{body}</script>", f"<script>{body}</script>".replace("\n", "\r\n"),
                 f"<script>{body}</script>".replace("\n", "\r")):
        assert f"'sha256-{expected}'" in server.page_csp(html)
