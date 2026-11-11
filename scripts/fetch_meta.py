"""Fetch tags, stars, dates and licenses into data/meta.json.

    python scripts/fetch_meta.py [--only id,id]
"""

import argparse
import datetime
import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import ghapi  # noqa: E402
from entries import ROOT, load_entries  # noqa: E402

GITHUB = re.compile(r"^https://github\.com/([^/]+)/([^/]+)$")

FIELDS = """
  id url isArchived stargazerCount createdAt description
  licenseInfo { spdxId }
  defaultBranchRef { name target { ... on Commit { committedDate } } }
  tags: refs(refPrefix: "refs/tags/", first: 100, orderBy: {field: TAG_COMMIT_DATE, direction: DESC}) {
    totalCount nodes { name target { oid ... on Tag { target { oid } } } } }
"""
RELEASE = re.compile(r"^v?(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:\.(\d+))?$")


def latest_tag(nodes):
    """The highest release version among the tags (newest first); the newest tag when none is one.

    A backport tagged after a newer release, and pre-releases such as v2.0.0-rc1, do not win.
    """
    best = None
    for n in nodes:
        m = RELEASE.match(n["name"])
        if m:
            key = tuple(int(g or 0) for g in m.groups())
            if best is None or key > best[0]:
                best = (key, n)
    return best[1] if best else (nodes[0] if nodes else None)


def commit_of(tag):
    """The commit a tag names; an annotated tag is an object of its own that points at it."""
    target = (tag or {}).get("target") or {}
    return (target.get("target") or {}).get("oid") or target.get("oid")


FAILED = "FAILED"


def fetch(batch):
    parts = [f"r{i}: repository(owner: {json.dumps(o)}, name: {json.dumps(r)}) {{ {FIELDS} }}"
             for i, (_, o, r) in enumerate(batch)]
    try:
        res = ghapi.graphql("query {" + "\n".join(parts) + "}", partial=True)
    except RuntimeError:
        return {id_: FAILED for id_, _, _ in batch}
    data = res.get("data") or {}
    # only NOT_FOUND means the repo is gone; anything else is a network error
    missing = {e["path"][0] for e in res.get("errors", []) if e.get("type") == "NOT_FOUND" and e.get("path")}
    return {id_: data.get(f"r{i}") if data.get(f"r{i}") is not None or f"r{i}" in missing else FAILED
            for i, (id_, _, _) in enumerate(batch)}


def to_meta(repo_url, node, old=None):
    # GitHub's id follows a repository through renames and transfers, and never passes to another one
    known = (old or {}).get("repo_id")
    if node is None:
        return {"exists": False, **({"repo_id": known} if known else {})}
    if known and node["id"] != known:
        # the address now holds a repository that is not the one listed: do not vouch for it
        return {"exists": False, "repo_id": known, "replaced_by": node["id"]}
    br = node.get("defaultBranchRef") or {}
    spdx = (node.get("licenseInfo") or {}).get("spdxId")
    tag = latest_tag(node["tags"]["nodes"] or [])
    m = {
        "exists": True,
        "repo_id": node["id"],
        "default_branch": br.get("name") or "",
        "latest_tag": tag["name"] if tag else None,
        "tag_count": node["tags"]["totalCount"],
        "created": node["createdAt"],
        "stars": node["stargazerCount"],
        "archived": node["isArchived"],
        "license": "none" if spdx is None else ("other" if spdx == "NOASSERTION" else spdx),
        "upstream_description": node.get("description"),
    }
    if (br.get("target") or {}).get("committedDate"):
        m["last_commit"] = br["target"]["committedDate"]
    if tag and commit_of(tag):
        m["latest_tag_commit"] = commit_of(tag)
    if node["url"].lower() != repo_url.lower():
        m["canonical_repo"] = node["url"]
    return m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="", help="entry ids to fetch, comma-separated; the rest keep their facts")
    only = {i.strip() for i in ap.parse_args().only.split(",") if i.strip()}
    entries = load_entries()
    todo = []
    for id_, (_, e) in entries.items():
        mt = GITHUB.match(e.get("repo") or "")
        if mt and (not only or id_ in only):
            todo.append((id_, mt.group(1), mt.group(2)))
    path = ROOT / "data" / "meta.json"
    old = json.loads(path.read_text(encoding="utf-8"))["entries"] if path.exists() else {}
    out = {id_: old[id_] for id_ in entries if only and id_ not in only and id_ in old}
    stale = []
    for i in range(0, len(todo), 30):
        batch = todo[i:i + 30]
        for id_, node in fetch(batch).items():
            if node == FAILED:
                stale.append(id_)
                if id_ in old:
                    out[id_] = old[id_]
                continue
            out[id_] = to_meta(entries[id_][1]["repo"], node, old.get(id_))
        print(f"  {min(i + 30, len(todo))}/{len(todo)}", flush=True)
    if stale:
        print(f"could not fetch {len(stale)}, kept previous facts where there were any: {stale}")
    doc = {"version": 1,
           "fetched_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "entries": dict(sorted(out.items()))}
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    gone = [k for k, v in out.items() if not v["exists"]]
    print(f"wrote {path.relative_to(ROOT)}: {len(out)} entries, {len(gone)} not found {gone}")


if __name__ == "__main__":
    main()
