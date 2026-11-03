"""Thin wrapper over the `gh` CLI: REST, paginated REST and GraphQL, with retries.

Uses whatever account `gh auth` is logged in as. Search endpoints are rate
limited (30/min for repos, 10/min for code), so callers pass `search=True` to
space those requests out.
"""

import json
import subprocess
import sys
import time

_last_search = {"repos": 0.0, "code": 0.0}
_SEARCH_GAP = {"repos": 2.2, "code": 6.5}


def _run(args, stdin=None):
    for attempt in range(6):
        p = subprocess.run(["gh", *args], input=stdin, capture_output=True, text=True, encoding="utf-8")
        if p.returncode == 0:
            return p.stdout
        err = p.stderr
        transient = ("rate limit", "secondary", "http 403", "http 500", "http 502", "http 503", "http 504",
                     "timeout", "wsarecv", "connection reset", "connection refused", "eof", "tls handshake",
                     "no such host", "i/o timeout", "connection attempt failed")
        if "api rate limit exceeded" in err.lower():
            wait = _until_reset()
            print(f"  gh: rate limit; waiting {wait}s for the reset", file=sys.stderr)
            time.sleep(wait)
            continue
        if any(t in err.lower() for t in transient):
            wait = 15 * (attempt + 1)
            print(f"  gh: {err.strip()[:120]} -- waiting {wait}s", file=sys.stderr)
            time.sleep(wait)
            continue
        if "HTTP 404" in err or "HTTP 409" in err or "HTTP 451" in err:
            return None
        raise RuntimeError(f"gh {' '.join(args)} failed: {err.strip()[:400]}")
    raise RuntimeError(f"gh {' '.join(args)}: gave up after retries")


def _until_reset():
    """Seconds until the exhausted rate limit resets (the rate_limit endpoint itself is free)."""
    p = subprocess.run(["gh", "api", "rate_limit"], capture_output=True, text=True, encoding="utf-8")
    try:
        res = json.loads(p.stdout)["resources"]
        resets = [r["reset"] for r in res.values() if r.get("remaining") == 0]
        return max(5, int(max(resets) - time.time()) + 5) if resets else 30
    except (ValueError, KeyError):
        return 60


def _space(kind):
    gap = _SEARCH_GAP[kind] - (time.time() - _last_search[kind])
    if gap > 0:
        time.sleep(gap)
    _last_search[kind] = time.time()


def rest(path, params=None, accept=None, raw=False):
    args = ["api", "-X", "GET", path]
    for k, v in (params or {}).items():
        args += ["-f", f"{k}={v}"]
    if accept:
        args += ["-H", f"Accept: {accept}"]
    out = _run(args)
    if out is None:
        return None
    return out if raw else json.loads(out)


def search(kind, q, max_results=1000):
    """kind is 'repositories' or 'code'. Returns the list of items."""
    items, page = [], 1
    while len(items) < max_results:
        _space("code" if kind == "code" else "repos")
        res = rest(f"search/{kind}", {"q": q, "per_page": 100, "page": page})
        if not res:
            break
        batch = res.get("items", [])
        items += batch
        if len(batch) < 100 or len(items) >= res.get("total_count", 0):
            break
        page += 1
    return items


def paginate(path, params=None):
    out, page = [], 1
    while True:
        p = dict(params or {}, per_page=100, page=page)
        batch = rest(path, p)
        if not batch:
            break
        out += batch
        if len(batch) < 100:
            break
        page += 1
    return out


def graphql(query, partial=False, **variables):
    """With partial=True, a response that has data and per-field errors (a repository
    that doesn't exist, in a batch of aliased lookups) is returned as is instead of
    raising, so one bad name doesn't fail its whole batch."""
    args = ["api", "graphql", "-f", f"query={query}"]
    for k, v in variables.items():
        args += ["-F" if isinstance(v, int) else "-f", f"{k}={v}"]
    if partial:
        for attempt in range(6):
            p = subprocess.run(["gh", *args], capture_output=True, text=True, encoding="utf-8")
            try:
                doc = json.loads(p.stdout)
            except ValueError:
                doc = None
            if doc and doc.get("data") is not None:
                return doc
            wait = _until_reset() if "rate limit" in p.stderr.lower() else 15 * (attempt + 1)
            print(f"  gh graphql: {p.stderr.strip()[:120]} -- waiting {wait}s", file=sys.stderr)
            time.sleep(wait)
        raise RuntimeError(f"graphql gave up: {p.stderr.strip()[:300]}")
    out = _run(args)
    return json.loads(out) if out else None
