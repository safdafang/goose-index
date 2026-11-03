"""Fetch the facts that change on their own into data/meta.json.

For every entry with a GitHub repo: default branch, its head commit date, the
newest tag, stars, archived, GitHub's license detection and the project's own
description (kept for validate.py's copy check). Run on a schedule; never edit
data/meta.json by hand.

    .venv/Scripts/python scripts/fetch_meta.py
"""

import datetime
import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import ghapi  # noqa: E402
from validate import load_entries  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
GITHUB = re.compile(r"^https://github\.com/([^/]+)/([^/]+)$")

FIELDS = """
  url isArchived stargazerCount createdAt description
  licenseInfo { spdxId }
  defaultBranchRef { name target { ... on Commit { committedDate } } }
  tags: refs(refPrefix: "refs/tags/", first: 1, orderBy: {field: TAG_COMMIT_DATE, direction: DESC}) {
    totalCount nodes { name } }
"""


FAILED = "FAILED"


def fetch(batch):
    parts = [f"r{i}: repository(owner: {json.dumps(o)}, name: {json.dumps(r)}) {{ {FIELDS} }}"
             for i, (_, o, r) in enumerate(batch)]
    try:
        res = ghapi.graphql("query {" + "\n".join(parts) + "}", partial=True)
    except RuntimeError:
        return {id_: FAILED for id_, _, _ in batch}
    data = res.get("data") or {}
    # only a NOT_FOUND error on an alias means the repository is gone; any other
    # gap is a network failure and must not be recorded as a fact
    missing = {e["path"][0] for e in res.get("errors", []) if e.get("type") == "NOT_FOUND" and e.get("path")}
    return {id_: data.get(f"r{i}") if data.get(f"r{i}") is not None or f"r{i}" in missing else FAILED
            for i, (id_, _, _) in enumerate(batch)}


def to_meta(repo_url, node):
    if node is None:
        return {"exists": False}
    br = node.get("defaultBranchRef") or {}
    spdx = (node.get("licenseInfo") or {}).get("spdxId")
    m = {
        "exists": True,
        "default_branch": br.get("name") or "",
        "latest_tag": (node["tags"]["nodes"] or [{}])[0].get("name"),
        "tag_count": node["tags"]["totalCount"],
        "created": node["createdAt"],
        "stars": node["stargazerCount"],
        "archived": node["isArchived"],
        "license": "none" if spdx is None else ("other" if spdx == "NOASSERTION" else spdx),
        "upstream_description": node.get("description"),
    }
    if (br.get("target") or {}).get("committedDate"):
        m["last_commit"] = br["target"]["committedDate"]
    if node["url"].lower() != repo_url.lower():
        m["canonical_repo"] = node["url"]
    return m


def main():
    entries = load_entries()
    todo = []
    for id_, (_, e) in entries.items():
        mt = GITHUB.match(e.get("repo") or "")
        if mt:
            todo.append((id_, mt.group(1), mt.group(2)))
    path = ROOT / "data" / "meta.json"
    old = json.loads(path.read_text(encoding="utf-8"))["entries"] if path.exists() else {}
    out, stale = {}, []
    for i in range(0, len(todo), 30):
        batch = todo[i:i + 30]
        for id_, node in fetch(batch).items():
            if node == FAILED:
                stale.append(id_)
                if id_ in old:  # keep the last good facts rather than invent new ones
                    out[id_] = old[id_]
                continue
            out[id_] = to_meta(entries[id_][1]["repo"], node)
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
